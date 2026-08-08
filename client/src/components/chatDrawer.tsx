import { AudioOutlined, CommentOutlined, SendOutlined, SoundOutlined, UnorderedListOutlined } from "@ant-design/icons";
import { useGetLocale, useTranslate } from "@refinedev/core";
import { Alert, Button, Drawer, FloatButton, Input, Space, Spin, Switch, Tag, Tooltip, Typography } from "antd";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router";
import { cardDiffRows, cardFieldLabel, cardValueMode, cardValueRows, formatCardValue } from "../utils/chatCardFields";
import {
  ChatConfirmCard,
  ChatExecutedCard,
  ChatMessage,
  ChatSpoolFilters,
  spoolListFilterLink,
  streamChat,
  useAIStatus,
  useChatAction,
  useTranscribe,
} from "../utils/queryAI";
import { parseBooleanSettingValue, useGetSettings } from "../utils/querySettings";
import { useCurrencyFormatter } from "../utils/settings";

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

const CARD_ROW_GRID: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "max-content 1fr",
  gap: "6px 18px",
  alignItems: "baseline",
  margin: "8px 0",
  fontSize: 13,
};

/**
 * A confirm-card's values (#378). A create or delete lists what is being added or removed, with
 * the rows that decide nothing left off; an update is a diff — one row per changed field, the
 * old value struck through beside the new one, so the reader is never asked to compare a
 * "Before" block against an "After" block by eye.
 */
function CardValues({ card }: { card: ChatConfirmCard }) {
  const t = useTranslate();
  const currency = useCurrencyFormatter();
  const context = { t, currency };

  const mode = cardValueMode(card.before, card.after);
  const rows =
    mode === "diff"
      ? cardDiffRows(card.before, card.after)
      : cardValueRows(mode === "create" ? card.after : mode === "delete" ? card.before : {});
  if (rows.length === 0) return null;

  return (
    <div style={CARD_ROW_GRID} data-testid="chat-card-values">
      {rows.map((row) => {
        const key = Array.isArray(row) ? row[0] : row.key;
        return (
          <React.Fragment key={key}>
            <Text type="secondary" data-testid={`chat-card-label-${key}`}>
              {cardFieldLabel(key, t)}
            </Text>
            <div data-testid={`chat-card-value-${key}`}>
              {Array.isArray(row) ? (
                formatCardValue(key, row[1], context)
              ) : (
                <>
                  <Text delete type="secondary">
                    {formatCardValue(key, row.before, context)}
                  </Text>
                  <Text type="secondary" style={{ margin: "0 7px" }}>
                    →
                  </Text>
                  {formatCardValue(key, row.after, context)}
                </>
              )}
            </div>
          </React.Fragment>
        );
      })}
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
  const status = useAIStatus();
  const enabled = parseBooleanSettingValue(settings.data?.ai_feature_chat?.value);
  const chatAction = useChatAction();
  const transcribe = useTranscribe();

  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<ChatItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState("");
  const [undone, setUndone] = useState<Set<number>>(new Set());
  // Voice input (#363): recording/transcribing state and the "speak replies" toggle.
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [speak, setSpeak] = useState(false);
  const speakRef = useRef(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const cancelRecordingRef = useRef(false);
  const wantStopRef = useRef(false);
  // The clean user/assistant transcript replayed to the server each turn (tool round-trips
  // stay server-side; a pending confirm carries its own full transcript instead).
  const transcript = useRef<ChatMessage[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  const context = useMemo(() => pageContext(location.pathname), [location.pathname]);

  const voiceEnabled = parseBooleanSettingValue(settings.data?.ai_feature_voice?.value);
  const micAvailable = voiceEnabled && status.data?.stt_configured === true;
  const autosend = parseBooleanSettingValue(settings.data?.ai_voice_autosend?.value);
  const speechAvailable = typeof window !== "undefined" && "speechSynthesis" in window;

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
          speakReply(event.data.content);
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

  const send = async (override?: string) => {
    const text = (override ?? draft).trim();
    if (!text || busy) return;
    setDraft("");
    push({ kind: "user", text });
    transcript.current.push({ role: "user", content: text });
    await runTurn({ messages: [...transcript.current] });
  };

  // --- Voice input (#363) ----------------------------------------------------------

  const speakReply = (text: string) => {
    if (!speakRef.current || !speechAvailable || !text) return;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
  };

  const toggleSpeak = (on: boolean) => {
    speakRef.current = on;
    setSpeak(on);
    if (!on && speechAvailable) window.speechSynthesis.cancel();
  };

  const handleTranscribe = async (audio: Blob) => {
    setTranscribing(true);
    try {
      const { text } = await transcribe.mutateAsync(audio);
      const clean = text.trim();
      if (!clean) return;
      // Transcribe-then-review by default (STT mangles vendor names); auto-send is opt-in.
      if (autosend) await send(clean);
      else setDraft((current) => (current ? `${current} ${clean}` : clean));
    } catch (error) {
      push({ kind: "error", text: String(error instanceof Error ? error.message : error) });
    } finally {
      setTranscribing(false);
    }
  };

  const startRecording = async () => {
    if (recording || transcribing || busy) return;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      push({ kind: "error", text: t("chat.voice.unsupported") });
      return;
    }
    setRecording(true);
    cancelRecordingRef.current = false;
    wantStopRef.current = false;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        setRecording(false);
        if (cancelRecordingRef.current) return;
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        if (blob.size > 0) void handleTranscribe(blob);
      };
      recorderRef.current = recorder;
      recorder.start();
      // The button may have been released before getUserMedia resolved — honour that stop.
      if (wantStopRef.current) recorder.stop();
    } catch {
      setRecording(false);
      push({ kind: "error", text: t("chat.voice.mic_error") });
    }
  };

  const stopRecording = (cancel: boolean) => {
    cancelRecordingRef.current = cancel;
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") recorder.stop();
    else wantStopRef.current = true;
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
                <CardValues card={card} />
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
        extra={
          voiceEnabled && speechAvailable ? (
            <Space size={4}>
              <SoundOutlined />
              <Text type="secondary" style={{ fontSize: 12 }}>
                {t("chat.voice.speak")}
              </Text>
              <Switch
                size="small"
                checked={speak}
                onChange={toggleSpeak}
                aria-label={t("chat.voice.speak")}
                data-testid="chat-speak-toggle"
              />
            </Space>
          ) : undefined
        }
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
          {micAvailable && (
            <Tooltip title={t("chat.voice.record")}>
              <Button
                icon={<AudioOutlined />}
                danger={recording}
                loading={transcribing}
                disabled={busy}
                onPointerDown={startRecording}
                onPointerUp={() => stopRecording(false)}
                onPointerLeave={() => recording && stopRecording(true)}
                aria-label={t("chat.voice.record")}
                data-testid="chat-mic"
              />
            </Tooltip>
          )}
          <Input
            value={draft}
            placeholder={recording ? t("chat.voice.listening") : t("chat.placeholder")}
            disabled={busy}
            onChange={(e) => setDraft(e.target.value)}
            onPressEnter={() => send()}
            data-testid="chat-input"
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            loading={busy}
            onClick={() => send()}
            aria-label={t("chat.send")}
          />
        </Space.Compact>
      </Drawer>
    </>
  );
}

export default ChatDrawer;
