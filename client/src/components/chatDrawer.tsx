import { AudioOutlined, ClearOutlined, MessageOutlined, SendOutlined } from "@ant-design/icons";
import { useGetLocale, useTranslate } from "@refinedev/core";
import { Alert, Button, Card, Descriptions, Drawer, FloatButton, Input, Space, Spin, Switch, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router";
import { AIChatEvent, AIChatPending, useAIChat, useAIStatus, useTranscribe } from "../utils/queryAI";
import { useGetSettings } from "../utils/querySettings";
import { useSavedState } from "../utils/saveload";
import { blobToBase64 } from "./photoIntake";

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
  const status = useAIStatus();
  const settings = useGetSettings();
  const transcribe = useTranscribe();

  const [transcript, setTranscript] = useState<unknown[]>([]);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [pending, setPending] = useState<AIChatPending | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Voice input (#363): the mic renders only when the feature is on, the server has
  // an STT endpoint configured, and this browser can actually record.
  const voiceEnabled = settings.data?.ai_feature_voice?.value === "true";
  const autoSend = settings.data?.ai_voice_auto_send?.value === "true";
  const micSupported =
    typeof MediaRecorder !== "undefined" && typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
  const micAvailable = voiceEnabled && status.data?.stt_configured === true && micSupported;
  const speakSupported = typeof window !== "undefined" && "speechSynthesis" in window;
  const [speakReplies, setSpeakReplies] = useSavedState("chatSpeakReplies", false);

  const [voiceState, setVoiceState] = useState<"idle" | "recording" | "transcribing">("idle");
  const [recordSeconds, setRecordSeconds] = useState(0);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const commitRef = useRef(false);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    const element = scrollRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [log, pending, chat.isPending]);

  // Stop any live recording if the panel unmounts mid-capture.
  useEffect(
    () => () => {
      if (timerRef.current !== null) window.clearInterval(timerRef.current);
      const recorder = recorderRef.current;
      if (recorder && recorder.state === "recording") {
        commitRef.current = false;
        recorder.stop();
      }
    },
    [],
  );

  const toolLabel = (tool: string) => (TOOL_LABEL_KEYS[tool] ? t(TOOL_LABEL_KEYS[tool]) : tool);

  const speak = (text: string) => {
    if (!speakSupported) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    if (locale) utterance.lang = locale;
    window.speechSynthesis.speak(utterance);
  };

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
      if (response.reply && voiceEnabled && speakSupported && speakReplies) speak(response.reply);
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setLog((entries) => entries.slice(0, entries.length - extraLog.length));
      return false;
    }
  };

  const sendText = async (text: string) => {
    if (!text || chat.isPending || pending) return;
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

  const send = async () => {
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    await sendText(text);
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

  // --- Push-to-talk (#363): hold to record, release to transcribe, slide away to cancel.

  const stopTimer = () => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  const finishRecording = async (mimeType: string) => {
    try {
      const blob = new Blob(chunksRef.current, { type: mimeType });
      const result = await transcribe.mutateAsync({
        audio_base64: await blobToBase64(blob),
        mime: mimeType,
        language: locale ?? undefined,
      });
      setVoiceState("idle");
      const text = result.text.trim();
      if (!text) return;
      // Transcribe-then-review is the default: the transcript lands editable in the
      // input box (STT mangles vendor names). Auto-send is an explicit settings opt-in.
      if (autoSend) {
        await sendText(text);
      } else {
        setDraft((previous) => (previous.trim() ? `${previous.trim()} ${text}` : text));
      }
    } catch (err) {
      setVoiceState("idle");
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const startRecording = async () => {
    if (voiceState !== "idle" || chat.isPending || pending) return;
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      recorderRef.current = recorder;
      chunksRef.current = [];
      commitRef.current = false;
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        stopTimer();
        if (commitRef.current) {
          void finishRecording(recorder.mimeType || "audio/webm");
        } else {
          setVoiceState("idle");
        }
      };
      recorder.start();
      setRecordSeconds(0);
      timerRef.current = window.setInterval(() => setRecordSeconds((seconds) => seconds + 1), 1000);
      setVoiceState("recording");
    } catch {
      setError(t("chat.voice.mic_error"));
      setVoiceState("idle");
    }
  };

  const stopRecording = (commit: boolean) => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state !== "recording") return;
    commitRef.current = commit;
    setVoiceState(commit ? "transcribing" : "idle");
    recorder.stop();
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }} data-testid="chat-panel">
      {voiceEnabled && speakSupported && (
        <div style={{ textAlign: "right", marginBottom: 4 }}>
          <Space size={6}>
            <Switch size="small" checked={speakReplies} onChange={setSpeakReplies} data-testid="chat-speak" />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t("chat.voice.speak_replies")}
            </Text>
          </Space>
        </div>
      )}
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
        {micAvailable && (
          <Button
            icon={voiceState === "transcribing" ? <Spin size="small" /> : <AudioOutlined />}
            danger={voiceState === "recording"}
            disabled={chat.isPending || pending !== null || voiceState === "transcribing"}
            onPointerDown={(event) => {
              event.preventDefault();
              void startRecording();
            }}
            onPointerUp={() => stopRecording(true)}
            onPointerLeave={() => stopRecording(false)}
            onContextMenu={(event) => event.preventDefault()}
            title={t("chat.voice.hold_to_talk")}
            data-testid="chat-mic"
          />
        )}
        {voiceState === "recording" ? (
          <div
            data-testid="voice-recording"
            style={{
              flex: 1,
              display: "flex",
              alignItems: "center",
              gap: 8,
              paddingInline: 11,
              border: "1px solid #ff4d4f",
              borderRadius: 6,
              minWidth: 0,
            }}
          >
            <Text type="danger" style={{ whiteSpace: "nowrap" }}>
              {t("chat.voice.recording")} {recordSeconds}s
            </Text>
            <Text type="secondary" style={{ marginLeft: "auto", fontSize: 12 }} ellipsis>
              {t("chat.voice.release_hint")}
            </Text>
          </div>
        ) : (
          <Input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onPressEnter={send}
            placeholder={voiceState === "transcribing" ? t("chat.voice.transcribing") : t("chat.placeholder")}
            disabled={chat.isPending || pending !== null || voiceState === "transcribing"}
            data-testid="chat-input"
          />
        )}
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={send}
          disabled={chat.isPending || pending !== null || voiceState !== "idle" || !draft.trim()}
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
