import { CheckCircleOutlined, DownloadOutlined } from "@ant-design/icons";
import { useTranslate } from "@refinedev/core";
import { Alert, Button, Progress, Space, Typography } from "antd";
import { useState } from "react";
import { AIProbeResult, pullOllamaModel } from "../../utils/queryAI";
import { RECOMMENDED_MODELS } from "./aiModels";

const { Text } = Typography;

// Managed model pull (#364 F2). Renders only when the probe identified the endpoint
// as an Ollama server - the one runtime whose API can list and pull models. We
// manage models, never the runtime: everything here drives Ollama's own API through
// the server, with per-model download sizes shown before anything is fetched.

type PullState = { kind: "pulling"; percent: number | null } | { kind: "done" } | { kind: "error"; message: string };

/** Installed check: Ollama's /v1/models lists tags like "qwen3:8b" (":latest" implied). */
function isInstalled(model: string, installedIds: string[]): boolean {
  const wanted = model.toLowerCase();
  return installedIds.some((id) => {
    const have = id.toLowerCase();
    return have === wanted || have === `${wanted}:latest` || `${have}:latest` === wanted;
  });
}

export function OllamaModelsSection(props: { capabilities: AIProbeResult; onPulled: () => void }) {
  const t = useTranslate();
  const [pulls, setPulls] = useState<Record<string, PullState>>({});

  const pull = async (model: string) => {
    setPulls((state) => ({ ...state, [model]: { kind: "pulling", percent: null } }));
    try {
      await pullOllamaModel(model, (progress) => {
        if (progress.total && progress.completed !== undefined) {
          const percent = Math.round((progress.completed / progress.total) * 100);
          setPulls((state) => ({ ...state, [model]: { kind: "pulling", percent } }));
        }
      });
      setPulls((state) => ({ ...state, [model]: { kind: "done" } }));
      // Refresh the probe so the installed state (and capability verdicts) update.
      props.onPulled();
    } catch (error) {
      setPulls((state) => ({
        ...state,
        [model]: { kind: "error", message: error instanceof Error ? error.message : String(error) },
      }));
    }
  };

  return (
    <div data-testid="ai-models-section" style={{ marginBottom: 16 }}>
      <Text strong>{t("settings.ai.models.title")}</Text>
      <div>
        <Text type="secondary">{t("settings.ai.models.hint")}</Text>
      </div>
      <Space direction="vertical" size={6} style={{ width: "100%", maxWidth: 640, marginTop: 8 }}>
        {RECOMMENDED_MODELS.map((entry) => {
          const installed = isInstalled(entry.model, props.capabilities.models);
          const state = pulls[entry.model];
          return (
            <div key={entry.model} style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <Text code>{entry.model}</Text>{" "}
                <Text type="secondary">
                  {t(entry.purposeKey)} - {t("settings.ai.models.size", { size: entry.sizeGB })}
                </Text>
                {state?.kind === "error" && (
                  <Alert type="error" showIcon message={state.message} style={{ marginTop: 4 }} />
                )}
              </div>
              {installed || state?.kind === "done" ? (
                <Text type="success" data-testid={`model-installed-${entry.model}`}>
                  <CheckCircleOutlined /> {t("settings.ai.models.installed")}
                </Text>
              ) : state?.kind === "pulling" ? (
                <div style={{ width: 140 }}>
                  <Progress
                    size="small"
                    percent={state.percent ?? 0}
                    status="active"
                    data-testid={`model-progress-${entry.model}`}
                  />
                </div>
              ) : (
                <Button
                  size="small"
                  icon={<DownloadOutlined />}
                  onClick={() => void pull(entry.model)}
                  data-testid={`model-pull-${entry.model}`}
                >
                  {t("settings.ai.models.pull")}
                </Button>
              )}
            </div>
          );
        })}
      </Space>
    </div>
  );
}
