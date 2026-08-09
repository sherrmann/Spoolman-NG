import { CheckCircleOutlined, DownloadOutlined } from "@ant-design/icons";
import { useTranslate } from "@refinedev/core";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Divider, List, Progress, Space, Tag, Typography, message } from "antd";
import { useState } from "react";
import { OllamaPullProgress, pullOllamaModel, useOllamaModels } from "../../utils/queryAI";
import { RECOMMENDED_MODELS } from "./aiModels";

const { Text, Paragraph } = Typography;

type PullState = OllamaPullProgress | "starting";

/**
 * Managed model pull (#364, F2): shown under Settings → AI when the configured endpoint is
 * an Ollama server. Lists a curated shortlist of recommended models with installed-vs-not
 * status and download size, and pulls one with live progress via Ollama's own API. Spoolman
 * manages models, never the runtime.
 */
export function OllamaModelsSection() {
  const t = useTranslate();
  const queryClient = useQueryClient();
  const models = useOllamaModels(true);
  const [pulling, setPulling] = useState<Record<string, PullState>>({});
  const [messageApi, contextHolder] = message.useMessage();

  const installed = new Set(models.data?.installed ?? []);

  const pull = async (model: string) => {
    setPulling((prev) => ({ ...prev, [model]: "starting" }));
    try {
      await pullOllamaModel(model, (event) => {
        if (event.event === "progress") setPulling((prev) => ({ ...prev, [model]: event.data }));
        else if (event.event === "error") messageApi.error(event.data.message);
      });
      messageApi.success(t("settings.ai.models.pulled", { model }));
    } catch (error) {
      messageApi.error(String(error instanceof Error ? error.message : error));
    } finally {
      setPulling((prev) => {
        const next = { ...prev };
        delete next[model];
        return next;
      });
      queryClient.invalidateQueries({ queryKey: ["ai-ollama-models"] });
    }
  };

  const renderAction = (model: string, downloadSizeGb: number) => {
    if (installed.has(model)) {
      return (
        <Tag color="success" icon={<CheckCircleOutlined />}>
          {t("settings.ai.models.installed")}
        </Tag>
      );
    }
    const progress = pulling[model];
    if (progress) {
      return (
        <div style={{ width: 160 }} data-testid={`progress-${model}`}>
          <Progress percent={progress === "starting" ? 0 : (progress.percent ?? 0)} size="small" status="active" />
        </div>
      );
    }
    return (
      <Button size="small" icon={<DownloadOutlined />} onClick={() => pull(model)} data-testid={`pull-${model}`}>
        {t("settings.ai.models.pull")} · {downloadSizeGb} GB
      </Button>
    );
  };

  return (
    <>
      {contextHolder}
      <Divider orientation="left">{t("settings.ai.models.title")}</Divider>
      <Paragraph type="secondary">{t("settings.ai.models.hint")}</Paragraph>
      <List
        size="small"
        dataSource={RECOMMENDED_MODELS}
        rowKey="model"
        renderItem={(entry) => (
          <List.Item actions={[renderAction(entry.model, entry.downloadSizeGb)]}>
            <List.Item.Meta
              title={
                <Space>
                  <Text code>{entry.model}</Text>
                  <Tag>{t(`settings.ai.models.purpose.${entry.purpose}`)}</Tag>
                </Space>
              }
              description={entry.note}
            />
          </List.Item>
        )}
      />
    </>
  );
}

export default OllamaModelsSection;
