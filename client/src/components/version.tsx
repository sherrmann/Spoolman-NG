import { useTranslate } from "@refinedev/core";
import { Spin, Tooltip, Typography } from "antd";
import { useInfo } from "../utils/useInfo";

const { Text, Link } = Typography;

export const Version = () => {
  const t = useTranslate();
  const infoResult = useInfo();

  if (infoResult.isLoading) {
    return <Spin />;
  }

  if (infoResult.isError || !infoResult.data) {
    return <span>{t("unknown")}</span>;
  }

  const info = infoResult.data;
  const commit_suffix = info.git_commit ? <Text type="secondary">{` (${info.git_commit})`}</Text> : <></>;

  // Subtle "update available" hint (#293): only when the server's daily check found a
  // newer release. Links to the release notes when we have a URL.
  const updateHint = info.update_available ? (
    <Tooltip title={info.latest_version ? t("update.tooltip", { version: info.latest_version }) : undefined}>
      {info.release_url ? (
        <Link href={info.release_url} target="_blank" rel="noopener noreferrer" style={{ marginLeft: 4 }}>
          {t("update.available")}
        </Link>
      ) : (
        <Text type="warning" style={{ marginLeft: 4 }}>
          {t("update.available")}
        </Text>
      )}
    </Tooltip>
  ) : null;

  return (
    <span title={info.build_date}>
      {info.version}
      {commit_suffix}
      {updateHint && <> — {updateHint}</>}
    </span>
  );
};
