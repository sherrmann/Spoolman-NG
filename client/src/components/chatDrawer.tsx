import { ClearOutlined, MessageOutlined, SendOutlined } from "@ant-design/icons";
import { useGetLocale, useTranslate } from "@refinedev/core";
import { Alert, Button, Card, Descriptions, Drawer, FloatButton, Input, Space, Spin, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router";
import { AIChatEvent, AIChatPending, useAIChat } from "../utils/queryAI";
import { useGetSettings } from "../utils/querySettings";

const { Text, Paragraph } = Typography;

// The in-app assistant (#362). Renders nothing unless the chat feature is enabled -
// invisible-unless-enabled, like every AI affordance. The conversation transcript
// lives here in component state and travels with every request; the server stores
// nothing. Mutating tool calls come back as pending actions and render as confirm
// cards - nothing is written until the user presses Confirm.

/** What the conversation column renders; the wire transcript is kept separately. */
type LogEntry =
  | { kind: "user"; text: string }
  | { kind: "assistant"; text: string }
  | { kind: "tools"; events: AIChatEvent[] }
  | { kind: "notice"; messageKey: string };

const TOOL_LABEL_KEYS: Record<string, string> = {
  find_spools: "chat.tools.find_spools",
  find_filaments: "chat.tools.find_filaments",
  get_inventory_stats: "chat.tools.get_inventory_stats",
  get_low_stock: "chat.tools.get_low_stock",
  use_spool_filament: "chat.tools.use_spool_filament",
  measure_spool: "chat.tools.measure_spool",
  create_spool: "chat.tools.create_spool",
  archive_spool: "chat.tools.archive_spool",
};

export function ChatPanel() {
  const t = useTranslate();
  const locale = useGetLocale()();
  const location = useLocation();
  const chat = useAIChat();

  const [transcript, setTranscript] = useState<unknown[]>([]);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [pending, setPending] = useState<AIChatPending | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = scrollRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [log, pending, chat.isPending]);

  const toolLabel = (tool: string) => (TOOL_LABEL_KEYS[tool] ? t(TOOL_LABEL_KEYS[tool]) : tool);

  const request = async (body: Parameters<typeof chat.mutateAsync>[0], extraLog: LogEntry[]): Promise<boolean> => {
    setError(null);
    // Optimistically show the user's side; rolled back if the request fails.
    setLog((entries) => [...entries, ...extraLog]);
    try {
      const response = await chat.mutateAsync(body);
      setTranscript(response.messages);
      setPending(response.pending);
      setLog((entries) => [
        ...entries,
        ...(response.events.length > 0 ? [{ kind: "tools", events: response.events } as LogEntry] : []),
        ...(response.reply ? [{ kind: "assistant", text: response.reply } as LogEntry] : []),
        ...(response.stopped_reason === "step_budget"
          ? [{ kind: "notice", messageKey: "chat.step_budget" } as LogEntry]
          : []),
      ]);
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setLog((entries) => entries.slice(0, entries.length - extraLog.length));
      return false;
    }
  };

  const send = async () => {
    const text = draft.trim();
    if (!text || chat.isPending || pending) return;
    setDraft("");
    const ok = await request(
      {
        messages: [...transcript, { role: "user", content: text }],
        context: { page: location.pathname, locale: locale ?? undefined },
      },
      [{ kind: "user", text }],
    );
    // Failed sends put the text back so the user can retry or edit it.
    if (!ok) setDraft(text);
  };

  const resolveAction = async (approved: boolean) => {
    if (!pending || chat.isPending) return;
    await request(
      {
        messages: transcript,
        context: { page: location.pathname, locale: locale ?? undefined },
        resolve: { id: pending.id, approved },
      },
      [{ kind: "notice", messageKey: approved ? "chat.action_confirmed" : "chat.action_declined" }],
    );
  };

  const clear = () => {
    setTranscript([]);
    setLog([]);
    setPending(null);
    setError(null);
    setDraft("");
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }} data-testid="chat-panel">
      <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", paddingRight: 4 }} data-testid="chat-messages">
        <Space direction="vertical" size="small" style={{ width: "100%" }}>
          {log.length === 0 && <Text type="secondary">{t("chat.empty")}</Text>}
          {log.map((entry, index) => {
            if (entry.kind === "user") {
              return (
                <div key={index} style={{ textAlign: "right" }}>
                  <Paragraph
                    style={{
                      display: "inline-block",
                      background: "rgba(128, 128, 128, 0.15)",
                      borderRadius: 8,
                      padding: "6px 10px",
                      marginBottom: 0,
                      whiteSpace: "pre-wrap",
                      textAlign: "left",
                    }}
                  >
                    {entry.text}
                  </Paragraph>
                </div>
              );
            }
            if (entry.kind === "assistant") {
              return (
                <Paragraph key={index} style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>
                  {entry.text}
                </Paragraph>
              );
            }
            if (entry.kind === "tools") {
              return (
                <div key={index}>
                  {entry.events.map((event, eventIndex) => (
                    <div key={eventIndex}>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {toolLabel(event.tool)}
                        {event.detail ? ` (${event.detail})` : ""}
                      </Text>
                    </div>
                  ))}
                </div>
              );
            }
            return (
              <Text key={index} type="secondary" style={{ fontSize: 12 }}>
                {t(entry.messageKey)}
              </Text>
            );
          })}
          {chat.isPending && (
            <Space>
              <Spin size="small" />
              <Text type="secondary">{t("chat.thinking")}</Text>
            </Space>
          )}
          {pending && !chat.isPending && (
            <Card size="small" title={t("chat.pending_title")} data-testid="chat-pending">
              <Space direction="vertical" size="small" style={{ width: "100%" }}>
                <Text strong>{toolLabel(pending.tool)}</Text>
                <Descriptions size="small" column={1} bordered>
                  {Object.entries(pending.arguments).map(([key, value]) => (
                    <Descriptions.Item key={key} label={key}>
                      {String(value)}
                    </Descriptions.Item>
                  ))}
                </Descriptions>
                <Space>
                  <Button type="primary" onClick={() => resolveAction(true)} data-testid="chat-confirm">
                    {t("chat.confirm")}
                  </Button>
                  <Button onClick={() => resolveAction(false)} data-testid="chat-decline">
                    {t("chat.cancel")}
                  </Button>
                </Space>
              </Space>
            </Card>
          )}
        </Space>
      </div>
      {error && <Alert type="error" showIcon message={error} style={{ marginTop: 8 }} />}
      {log.length > 0 && (
        <div style={{ textAlign: "right", marginTop: 4 }}>
          <Button type="text" size="small" icon={<ClearOutlined />} onClick={clear} data-testid="chat-clear">
            {t("chat.clear")}
          </Button>
        </div>
      )}
      <Space.Compact style={{ marginTop: 8, width: "100%" }}>
        <Input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onPressEnter={send}
          placeholder={t("chat.placeholder")}
          disabled={chat.isPending || pending !== null}
          data-testid="chat-input"
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={send}
          disabled={chat.isPending || pending !== null || !draft.trim()}
          data-testid="chat-send"
        />
      </Space.Compact>
    </div>
  );
}

/**
 * Floating chat affordance for the global chrome, stacked above the scan button.
 * Renders nothing while the chat feature is disabled.
 */
const ChatDrawer = () => {
  const t = useTranslate();
  const settings = useGetSettings();
  const [open, setOpen] = useState(false);

  if (settings.data?.ai_feature_chat?.value !== "true") return null;

  return (
    <>
      <FloatButton
        onClick={() => setOpen(true)}
        icon={<MessageOutlined />}
        shape="circle"
        style={{ insetBlockEnd: 104 }}
        data-testid="chat-fab"
      />
      <Drawer
        title={t("chat.title")}
        open={open}
        onClose={() => setOpen(false)}
        width={Math.min(420, window.innerWidth)}
        styles={{ body: { display: "flex", flexDirection: "column" } }}
        destroyOnHidden={false}
        data-testid="chat-drawer"
      >
        <ChatPanel />
      </Drawer>
    </>
  );
};

export default ChatDrawer;
