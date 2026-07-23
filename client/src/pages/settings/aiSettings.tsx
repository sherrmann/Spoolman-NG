import { CheckCircleOutlined, CloseCircleOutlined, CopyOutlined, QuestionCircleOutlined } from "@ant-design/icons";
import { useTranslate } from "@refinedev/core";
import { useQueryClient } from "@tanstack/react-query";
import { Alert, AutoComplete, Button, Checkbox, Divider, Form, Input, Select, Space, Typography, message } from "antd";
import { useEffect, useState } from "react";
import { useAuthStatus } from "../../utils/auth";
import { AIProbeResult, AITriState, useAIProbe, useAIStatus, useSetAIKey } from "../../utils/queryAI";
import { useGetSettings, useSetSetting } from "../../utils/querySettings";
import { getBasePath } from "../../utils/url";
import { AI_PRESETS } from "./aiPresets";

const { Text, Paragraph } = Typography;

// Feature toggles rendered in the panel. Each persists a registered BOOLEAN setting;
// the features themselves (#360-#363) render nothing anywhere until these are on.
const FEATURE_ROWS: {
  settingKey: string;
  statusKey: string;
  labelKey: string;
  requiresVision?: boolean;
  unavailable?: boolean;
}[] = [
  { settingKey: "ai_feature_chat", statusKey: "chat", labelKey: "settings.ai.features.chat" },
  {
    settingKey: "ai_feature_scan_to_spool",
    statusKey: "scan_to_spool",
    labelKey: "settings.ai.features.scan_to_spool",
    requiresVision: true,
  },
  { settingKey: "ai_feature_nl_search", statusKey: "nl_search", labelKey: "settings.ai.features.nl_search" },
  { settingKey: "ai_feature_voice", statusKey: "voice", labelKey: "settings.ai.features.voice", unavailable: true },
];

function TriStateRow(props: { labelKey: string; value: AITriState }) {
  const t = useTranslate();
  const icon =
    props.value === "yes" ? (
      <CheckCircleOutlined style={{ color: "#52c41a" }} />
    ) : props.value === "no" ? (
      <CloseCircleOutlined style={{ color: "#ff4d4f" }} />
    ) : (
      <QuestionCircleOutlined />
    );
  return (
    <div>
      {icon} {t(props.labelKey)}: {t(`settings.ai.probe.${props.value}`)}
    </div>
  );
}

export function AISettings() {
  const t = useTranslate();
  const queryClient = useQueryClient();
  const status = useAIStatus();
  const settings = useGetSettings();
  const probe = useAIProbe();
  const setKey = useSetAIKey();
  const setBaseUrl = useSetSetting<string>("ai_base_url");
  const setModel = useSetSetting<string>("ai_model");
  const setVisionModel = useSetSetting<string>("ai_vision_model");
  const featureMutations = {
    ai_feature_chat: useSetSetting<boolean>("ai_feature_chat"),
    ai_feature_scan_to_spool: useSetSetting<boolean>("ai_feature_scan_to_spool"),
    ai_feature_nl_search: useSetSetting<boolean>("ai_feature_nl_search"),
    ai_feature_voice: useSetSetting<boolean>("ai_feature_voice"),
  } as Record<string, ReturnType<typeof useSetSetting<boolean>>>;
  const setMcpEnabled = useSetSetting<boolean>("mcp_enabled");
  const authStatus = useAuthStatus();
  const [form] = Form.useForm();
  const [messageApi, contextHolder] = message.useMessage();
  // The most recent probe: either just run from this form, or the server-cached one.
  const [probeResult, setProbeResult] = useState<AIProbeResult | null>(null);
  const capabilities = probeResult ?? status.data?.capabilities ?? null;
  const envLocked = new Set(status.data?.env_locked ?? []);

  useEffect(() => {
    if (status.data) {
      form.setFieldsValue({
        base_url: status.data.base_url ?? "",
        model: status.data.model ?? "",
        vision_model: status.data.vision_model ?? "",
      });
    }
    // The api_key field is deliberately never populated: the server never returns it.
  }, [status.data, form]);

  const applyPreset = (key: string) => {
    const preset = AI_PRESETS.find((entry) => entry.key === key);
    if (preset && !envLocked.has("base_url")) {
      form.setFieldValue("base_url", preset.baseUrl);
    }
  };

  const runProbe = async () => {
    const values = form.getFieldsValue();
    const overrides: Record<string, string> = {};
    for (const field of ["base_url", "model", "vision_model"] as const) {
      if (!envLocked.has(field)) overrides[field] = values[field] ?? "";
    }
    // Only send a key override when the user typed one; otherwise the stored/env key is used.
    if (values.api_key) overrides.api_key = values.api_key;
    probe.mutate(overrides, { onSuccess: setProbeResult });
  };

  const onFinish = async (values: { base_url?: string; model?: string; vision_model?: string; api_key?: string }) => {
    try {
      if (!envLocked.has("base_url")) await setBaseUrl.mutateAsync(values.base_url ?? "");
      if (!envLocked.has("model")) await setModel.mutateAsync(values.model ?? "");
      if (!envLocked.has("vision_model")) await setVisionModel.mutateAsync(values.vision_model ?? "");
      if (values.api_key) {
        await setKey.mutateAsync(values.api_key);
        form.setFieldValue("api_key", "");
      }
      messageApi.success(t("notifications.saveSuccessful"));
    } catch (error) {
      messageApi.error(String(error));
    }
    // Saved values change the effective config (configured flag, env fallbacks).
    queryClient.invalidateQueries({ queryKey: ["ai-status"] });
  };

  const modelOptions = (capabilities?.models ?? []).map((id) => ({ value: id }));
  const envLockedHint = (field: string) =>
    envLocked.has(field) ? <Text type="secondary">{t("settings.ai.env_locked")}</Text> : undefined;

  const mcpEnabledRaw = settings.data?.mcp_enabled?.value;
  const mcpEnabled = mcpEnabledRaw !== undefined ? JSON.parse(mcpEnabledRaw) === true : false;
  const mcpUrl = `${window.location.origin}${getBasePath()}/mcp`;
  const copyMcpConfig = async () => {
    const server: Record<string, unknown> = { type: "http", url: mcpUrl };
    if (authStatus.data?.auth_required) {
      // The MCP endpoint accepts the same bearer tokens as the API.
      server.headers = { Authorization: "Bearer YOUR_SPOOLMAN_TOKEN" };
    }
    await navigator.clipboard.writeText(JSON.stringify({ mcpServers: { spoolman: server } }, null, 2));
    messageApi.success(t("settings.ai.mcp.copied"));
  };

  return (
    <>
      {contextHolder}
      <Paragraph type="secondary">{t("settings.ai.description")}</Paragraph>
      <Form form={form} labelCol={{ span: 8 }} wrapperCol={{ span: 16 }} onFinish={onFinish}>
        <Form.Item label={t("settings.ai.preset.label")}>
          <Select
            placeholder={t("settings.ai.preset.placeholder")}
            options={AI_PRESETS.map((preset) => ({ value: preset.key, label: preset.label }))}
            onChange={applyPreset}
            disabled={envLocked.has("base_url")}
            data-testid="ai-preset"
          />
        </Form.Item>
        <Form.Item
          label={t("settings.ai.base_url.label")}
          tooltip={t("settings.ai.base_url.tooltip")}
          name="base_url"
          extra={envLockedHint("base_url")}
          rules={[{ pattern: /^https?:\/\/.+$/, message: t("settings.ai.base_url.invalid") }]}
        >
          <Input placeholder="http://localhost:11434/v1" disabled={envLocked.has("base_url")} />
        </Form.Item>
        <Form.Item
          label={t("settings.ai.api_key.label")}
          name="api_key"
          extra={envLockedHint("api_key")}
          tooltip={t("settings.ai.api_key.tooltip")}
        >
          <Input.Password
            placeholder={
              status.data?.api_key_set
                ? t("settings.ai.api_key.placeholder_set")
                : t("settings.ai.api_key.placeholder_unset")
            }
            disabled={envLocked.has("api_key")}
            autoComplete="off"
          />
        </Form.Item>
        {status.data?.api_key_set && !envLocked.has("api_key") && (
          <Form.Item wrapperCol={{ offset: 8, span: 16 }}>
            <Button size="small" loading={setKey.isPending} onClick={() => setKey.mutate(null)}>
              {t("settings.ai.api_key.clear")}
            </Button>
          </Form.Item>
        )}
        <Form.Item
          label={t("settings.ai.model.label")}
          name="model"
          extra={envLockedHint("model")}
          tooltip={t("settings.ai.model.tooltip")}
        >
          <AutoComplete options={modelOptions} disabled={envLocked.has("model")} />
        </Form.Item>
        <Form.Item
          label={t("settings.ai.vision_model.label")}
          name="vision_model"
          extra={envLockedHint("vision_model")}
          tooltip={t("settings.ai.vision_model.tooltip")}
        >
          <AutoComplete options={modelOptions} disabled={envLocked.has("vision_model")} />
        </Form.Item>
        <Form.Item wrapperCol={{ offset: 8, span: 16 }}>
          <Space>
            <Button type="primary" htmlType="submit" loading={setBaseUrl.isPending || setKey.isPending}>
              {t("buttons.save")}
            </Button>
            <Button onClick={runProbe} loading={probe.isPending}>
              {t("settings.ai.test")}
            </Button>
          </Space>
        </Form.Item>
      </Form>

      {probe.isError && <Alert type="error" showIcon message={String(probe.error)} />}
      {capabilities && (
        <div data-testid="ai-probe-result" style={{ marginBottom: 16 }}>
          {capabilities.ok ? (
            <Space direction="vertical" size={4}>
              <div>
                <CheckCircleOutlined style={{ color: "#52c41a" }} /> {t("settings.ai.probe.reachable")}
                {capabilities.latency_ms != null && <Text type="secondary"> ({capabilities.latency_ms} ms)</Text>}
                {capabilities.models.length > 0 && (
                  <Text type="secondary">
                    {" "}
                    - {t("settings.ai.probe.models_listed")}: {capabilities.models.length}
                  </Text>
                )}
              </div>
              <TriStateRow labelKey="settings.ai.probe.chat" value={capabilities.chat} />
              <TriStateRow labelKey="settings.ai.probe.tools" value={capabilities.tools} />
              <TriStateRow labelKey="settings.ai.probe.vision" value={capabilities.vision} />
            </Space>
          ) : (
            <Alert type="warning" showIcon message={capabilities.error ?? t("settings.ai.probe.failed")} />
          )}
        </div>
      )}

      <Divider orientation="left">{t("settings.ai.features.title")}</Divider>
      <Paragraph type="secondary">{t("settings.ai.features.hint")}</Paragraph>
      <Space direction="vertical" size={8}>
        {FEATURE_ROWS.map((row) => {
          // Read from the settings query: useSetSetting updates it optimistically, so the
          // checkbox reacts instantly; /ai/status mirrors the same values for other consumers.
          const rawValue = settings.data?.[row.settingKey]?.value;
          const enabled = rawValue !== undefined ? JSON.parse(rawValue) === true : false;
          let reasonKey: string | null = null;
          if (row.unavailable) {
            reasonKey = "settings.ai.features.voice_unavailable";
          } else if (!status.data?.configured) {
            reasonKey = "settings.ai.features.requires_config";
          } else if (row.requiresVision && capabilities?.vision === "no") {
            reasonKey = "settings.ai.features.requires_vision";
          }
          // A blocked toggle can always be turned OFF, never ON.
          const disabled = reasonKey !== null && !enabled;
          return (
            <div key={row.settingKey}>
              <Checkbox
                checked={enabled}
                disabled={disabled}
                onChange={(event) => featureMutations[row.settingKey].mutate(event.target.checked)}
                data-testid={`toggle-${row.statusKey}`}
              >
                {t(row.labelKey)}
              </Checkbox>
              {reasonKey && (
                <div>
                  <Text type="secondary" style={{ marginLeft: 24 }}>
                    {t(reasonKey)}
                  </Text>
                </div>
              )}
            </div>
          );
        })}
      </Space>

      <Divider orientation="left">{t("settings.ai.mcp.title")}</Divider>
      <Paragraph type="secondary">{t("settings.ai.mcp.description")}</Paragraph>
      <Space direction="vertical" size={8} style={{ width: "100%", maxWidth: 640 }}>
        <Checkbox
          checked={mcpEnabled}
          onChange={(event) => setMcpEnabled.mutate(event.target.checked)}
          data-testid="toggle-mcp"
        >
          {t("settings.ai.mcp.enable")}
        </Checkbox>
        {mcpEnabled && (
          <>
            <Space.Compact style={{ width: "100%" }}>
              <Input readOnly value={mcpUrl} data-testid="mcp-url" />
              <Button icon={<CopyOutlined />} onClick={copyMcpConfig} data-testid="mcp-copy">
                {t("settings.ai.mcp.copy_config")}
              </Button>
            </Space.Compact>
            {authStatus.data?.auth_required && <Text type="secondary">{t("settings.ai.mcp.auth_note")}</Text>}
          </>
        )}
      </Space>
    </>
  );
}
