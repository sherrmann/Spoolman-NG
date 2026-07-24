import { RobotOutlined } from "@ant-design/icons";
import { useGetLocale, useTranslate } from "@refinedev/core";
import { Alert, Button, Input, Popover, Space, Typography } from "antd";
import { useState } from "react";
import { NlSearchResult, useNlSearch } from "../utils/queryAI";
import { useGetSettings } from "../utils/querySettings";

const { Text } = Typography;

/**
 * The natural-language search entry point (#362, B2): an [AI] button beside the spool
 * search box, shown only while `ai_feature_nl_search` is on. Free text is translated into
 * the list's existing filter model server-side and handed to `onApply`, which sets the
 * ordinary (editable) filters — the AI never replaces the normal filter UI, it just fills
 * it in. An empty result set means nothing mapped; the caller falls back to a text search.
 */
export function NlSearchButton({
  onApply,
  defaultQuery,
}: {
  onApply: (result: NlSearchResult) => void;
  defaultQuery?: string;
}) {
  const t = useTranslate();
  const getLocale = useGetLocale();
  const settings = useGetSettings();
  const enabled = settings.data?.ai_feature_nl_search?.value === "true";
  const nlSearch = useNlSearch();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState(defaultQuery ?? "");

  if (!enabled) return null;

  const run = async () => {
    const trimmed = query.trim();
    if (!trimmed) return;
    try {
      const result = await nlSearch.mutateAsync({ query: trimmed, locale: getLocale() ?? "en" });
      onApply(result);
      setOpen(false);
    } catch {
      // The inline Alert renders the error; keep the popover open so the user can retry.
    }
  };

  const content = (
    <div style={{ width: 280 }}>
      <Input
        autoFocus
        value={query}
        placeholder={t("spool.nlSearch.placeholder")}
        onChange={(e) => setQuery(e.target.value)}
        onPressEnter={run}
        data-testid="nl-search-input"
      />
      <Space style={{ marginTop: 8, width: "100%", justifyContent: "space-between" }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {t("spool.nlSearch.hint")}
        </Text>
        <Button type="primary" size="small" loading={nlSearch.isPending} onClick={run}>
          {t("spool.nlSearch.search")}
        </Button>
      </Space>
      {nlSearch.isError && <Alert type="error" showIcon style={{ marginTop: 8 }} message={t("spool.nlSearch.error")} />}
    </div>
  );

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      trigger="click"
      placement="bottomRight"
      title={t("spool.nlSearch.title")}
      content={content}
    >
      <Button icon={<RobotOutlined />} data-testid="nl-search-button">
        {t("spool.nlSearch.button")}
      </Button>
    </Popover>
  );
}

export default NlSearchButton;
