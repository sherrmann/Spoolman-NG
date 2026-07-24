import { CommentOutlined, SendOutlined, UnorderedListOutlined } from "@ant-design/icons";
import { useGetLocale, useTranslate } from "@refinedev/core";
import { Alert, Button, Drawer, FloatButton, Input, Space, Spin, Tag, Typography } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router";
import {
  ChatConfirmCard,
  ChatExecutedCard,
  ChatMessage,
  ChatSpoolFilters,
  spoolListFilterLink,
  streamChat,
  useChatAction,
} from "../utils/queryAI";
import { useGetSettings } from "../utils/querySettings";

const { Text, Paragraph } = Typography;

// Map the current route to a short human context string the assistant is told about, so a
// question like "how much of this do I have?" can be read against the page the user is on.
function pageContext(pathname: string): string | undefined {
  if (pathname.includes("/spool")) return "Spools list";
  if (pathname.includes("/filament")) return "Filaments list";
  if (pathname.includes("/manufacturer") || pathname.includes("/vendor")) return "Manufacturers list";
  if (pathname.includes("/location")) return "Locations list";
  if (pathname.includes("lowstock") || pathname.includes("low-stock") || pathname.includes("low_stock")) {
    return "Low-stock view";
  }
  return undefined;
}

type ChatItem =
  | { id: number; kind: "user"; text: string }
  | { id: number; kind: "assistant"; text: string; filters?: ChatSpoolFilters }
  | { id: number; kind: "tool"; text: string }
  | { id: number; kind: "confirm"; cards: ChatConfirmCard[]; messages: ChatMessage[]; resolved?: "confirm" | "cancel" }
  | { id: number; kind: "executed"; cards: ChatExecutedCard[] }
  | { id: number; kind: "error"; text: string };

// Distributive Omit so `Omit<…, "id">` keeps each discriminated-union variant's own shape
// (a plain Omit over a union collapses it to just the common keys).
type DistributiveOmit<T, K extends keyof T> = T extends unknown ? Omit<T, K> : never;

let nextId = 1;
const makeId = () => nextId++;

/** A before/after key/value block for a confirm-card. */
function ValueBlock({ label, values }: { label: string; values: Record<string, unknown> }) {
  const entries = Object.entries(values);
  if (entries.length === 0) return null;
  return (
    <div>
      <Text type="secondary" style={{ fontSize: 12 }}>
        {label}
      </Text>
      {entries.map(([key, value]) => (
        <div key={key} style={{ fontSize: 13 }}>
          <Text type="secondary">{key}:</Text> <Text code>{value === null ? "∅" : String(value)}</Text>
        </div>
      ))}
    </div>
  );
}

/**
 * The chat assistant (#362, B1): a second floating button that opens a right-side drawer
 * on every page. Renders only while the `ai_feature_chat` toggle is on. Mutations arrive
 * as confirm-cards that must be confirmed before anything changes, with a one-click undo
 * after execution.
 */
export function ChatDrawer() {
  const t = useTranslate();
  const getLocale = useGetLocale();
  const location = useLocation();
  const settings = useGetSettings();
  const enabled = settings.data?.ai_feature_chat?.value === "true";
  const chatAction = useChatAction();

  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<ChatItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState("");
  const [undone, setUndone] = useState<Set<number>>(new Set());
  // The clean user/assistant transcript replayed to the server each turn (tool round-trips
  // stay server-side; a pending confirm carries its own full transcript instead).
  const transcript = useRef<ChatMessage[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  const context = useMemo(() => pageContext(location.pathname), [location.pathname]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [items, busy]);

  if (!enabled) return null;

  const push = (item: DistributiveOmit<ChatItem, "id">) =>
    setItems((prev) => [...prev, { ...item, id: makeId() } as ChatItem]);

  const runTurn = async (body: Parameters<typeof streamChat>[0]) => {
    setBusy(true);
    let pendingFilters: ChatSpoolFilters | undefined;
    try {
      await streamChat({ ...body, context, locale: getLocale() ?? "en" }, (event) => {
        if (event.event === "tool") {
          push({ kind: "tool", text: event.data.summary });
          if (event.data.filters) pendingFilters = event.data.filters;
        } else if (event.event === "message") {
          push({ kind: "assistant", text: event.data.content, filters: pendingFilters });
          transcript.current.push({ role: "assistant", content: event.data.content });
          pendingFilters = undefined;
        } else if (event.event === "confirm") {
          push({ kind: "confirm", cards: event.data.cards, messages: event.data.messages });
        } else if (event.event === "executed") {
          push({ kind: "executed", cards: event.data.cards });
        } else if (event.event === "error") {
          push({ kind: "error", text: event.data.message });
        }
      });
    } catch (error) {
      push({ kind: "error", text: String(error instanceof Error ? error.message : error) });
    } finally {
      setBusy(false);
    }
  };

  const send = async () => {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    push({ kind: "user", text });
    transcript.current.push({ role: "user", content: text });
    await runTurn({ messages: [...transcript.current] });
  };

  const resolveConfirm = async (item: Extract<ChatItem, { kind: "confirm" }>, decision: "confirm" | "cancel") => {
    if (busy || item.resolved) return;
    setItems((prev) => prev.map((it) => (it.id === item.id ? { ...it, resolved: decision } : it)));
    await runTurn({ messages: item.messages, decision });
  };

  const undo = async (itemId: number, action: NonNullable<ChatExecutedCard["undo"]>) => {
    try {
      await chatAction.mutateAsync(action);
      setUndone((prev) => new Set(prev).add(itemId));
      push({ kind: "assistant", text: t("chat.executed.undone") });
    } catch (error) {
      push({ kind: "error", text: String(error instanceof Error ? error.message : error) });
    }
  };

  const renderItem = (item: ChatItem) => {
    switch (item.kind) {
      case "user":
        return (
          <div key={item.id} style={{ textAlign: "right", margin: "6px 0" }}>
            <Text
              style={{
                display: "inline-block",
                background: "rgba(140,140,140,0.18)",
                padding: "6px 10px",
                borderRadius: 10,
              }}
            >
              {item.text}
            </Text>
          </div>
        );
      case "assistant": {
        const link = item.filters ? spoolListFilterLink(item.filters) : null;
        return (
          <div key={item.id} style={{ margin: "6px 0" }}>
            <Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: link ? 4 : 0 }}>{item.text}</Paragraph>
            {link && (
              <Button size="small" icon={<UnorderedListOutlined />} href={link}>
                {t("chat.viewInList")}
              </Button>
            )}
          </div>
        );
      }
      case "tool":
        return (
          <div key={item.id} style={{ margin: "2px 0" }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {item.text}
            </Text>
          </div>
        );
      case "error":
        return <Alert key={item.id} type="error" showIcon message={item.text} style={{ margin: "6px 0" }} />;
      case "executed":
        return (
          <div key={item.id} style={{ margin: "6px 0" }}>
            {item.cards.map((card, index) => (
              <Space key={index} size="small" wrap>
                <Text type="success">{card.summary}</Text>
                {card.undo && (
                  <Button
                    size="small"
                    disabled={undone.has(item.id) || chatAction.isPending}
                    onClick={() => undo(item.id, card.undo!)}
                  >
                    {undone.has(item.id) ? t("chat.executed.undone") : t("chat.executed.undo")}
                  </Button>
                )}
              </Space>
            ))}
          </div>
        );
      case "confirm":
        return (
          <div
            key={item.id}
            style={{ margin: "8px 0", border: "1px solid rgba(140,140,140,0.35)", borderRadius: 10, padding: 12 }}
          >
            {item.cards.map((card, index) => (
              <div key={index} style={{ marginBottom: index < item.cards.length - 1 ? 12 : 0 }}>
                <Space align="center">
                  <Text strong>{card.title}</Text>
                  {card.destructive && <Tag color="red">{t("chat.confirm.destructive")}</Tag>}
                </Space>
                <Paragraph type="secondary" style={{ margin: "4px 0", fontSize: 13 }}>
                  {card.summary}
                </Paragraph>
                <Space size="large" align="start">
                  <ValueBlock label={t("chat.confirm.before")} values={card.before} />
                  <ValueBlock label={t("chat.confirm.after")} values={card.after} />
                </Space>
              </div>
            ))}
            <Space style={{ marginTop: 10 }}>
              <Button
                type="primary"
                danger={item.cards.some((c) => c.destructive)}
                disabled={!!item.resolved || busy}
                onClick={() => resolveConfirm(item, "confirm")}
              >
                {t("chat.confirm.confirm")}
              </Button>
              <Button disabled={!!item.resolved || busy} onClick={() => resolveConfirm(item, "cancel")}>
                {t("chat.confirm.cancel")}
              </Button>
              {item.resolved && (
                <Text type="secondary">
                  {item.resolved === "confirm" ? t("chat.confirm.confirmed") : t("chat.confirm.cancelled")}
                </Text>
              )}
            </Space>
          </div>
        );
    }
  };

  return (
    <>
      <FloatButton
        icon={<CommentOutlined />}
        type="primary"
        shape="circle"
        style={{ insetBlockEnd: 96 }}
        tooltip={t("chat.open")}
        aria-label={t("chat.open")}
        onClick={() => setOpen(true)}
      />
      <Drawer
        title={t("chat.title")}
        open={open}
        onClose={() => setOpen(false)}
        width={420}
        styles={{ body: { display: "flex", flexDirection: "column", padding: 12 } }}
      >
        <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", paddingRight: 4 }}>
          {items.length === 0 && (
            <Paragraph type="secondary" data-testid="chat-empty">
              {t("chat.empty")}
            </Paragraph>
          )}
          {items.map(renderItem)}
          {busy && (
            <div style={{ margin: "6px 0" }}>
              <Spin size="small" /> <Text type="secondary">{t("chat.thinking")}</Text>
            </div>
          )}
        </div>
        <Space.Compact style={{ marginTop: 8 }}>
          <Input
            value={draft}
            placeholder={t("chat.placeholder")}
            disabled={busy}
            onChange={(e) => setDraft(e.target.value)}
            onPressEnter={send}
            data-testid="chat-input"
          />
          <Button type="primary" icon={<SendOutlined />} loading={busy} onClick={send} aria-label={t("chat.send")} />
        </Space.Compact>
      </Drawer>
    </>
  );
}

export default ChatDrawer;
