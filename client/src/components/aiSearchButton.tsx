import { useTranslate } from "@refinedev/core";
import { Alert, Button, Input, Popover, Space, Typography } from "antd";
import { useState } from "react";
import { AISearchFilters, useAISearch } from "../utils/queryAI";
import { useGetSettings } from "../utils/querySettings";

const { Text } = Typography;

// Natural-language search (#362 B2). The button renders only while the feature is
// enabled. The reply is not a black box: the server validates it against the
// install's real filter values, and the caller applies it as the ordinary,
// editable filter state - the same funnel icons, search box and color chip the
// user could have set by hand. Anything inexpressible is reported, not guessed.

export function AISearchButton(props: {
  entity: "spool" | "filament";
  onApply: (filters: AISearchFilters, dropped: string[]) => void;
}) {
  const t = useTranslate();
  const settings = useGetSettings();
  const search = useAISearch();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (settings.data?.ai_feature_nl_search?.value !== "true") return null;

  const run = async (value: string) => {
    const trimmed = value.trim();
    if (!trimmed || search.isPending) return;
    setError(null);
    try {
      const result = await search.mutateAsync({ entity: props.entity, query: trimmed });
      props.onApply(result.filters, result.dropped);
      setOpen(false);
      setQuery("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setError(null);
      }}
      trigger="click"
      content={
        <Space direction="vertical" size="small" style={{ width: 320 }}>
          {error && <Alert type="error" showIcon message={error} />}
          <Input.Search
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onSearch={run}
            placeholder={t("aisearch.placeholder")}
            enterButton={t("aisearch.apply")}
            loading={search.isPending}
            autoFocus
            data-testid="ai-search-input"
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t("aisearch.hint")}
          </Text>
        </Space>
      }
    >
      <Button data-testid="ai-search-button" title={t("aisearch.tooltip")}>
        {t("aisearch.button")}
      </Button>
    </Popover>
  );
}
