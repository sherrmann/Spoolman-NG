import { useTranslate } from "@refinedev/core";
import { Button, Spin, Tooltip, Typography } from "antd";
import { useUpdateModal } from "../utils/updateAction";
import { useInfo } from "../utils/useInfo";

const { Text } = Typography;

export const Version = () => {
  const t = useTranslate();
  const infoResult = useInfo();
  const showUpdateModal = useUpdateModal((s) => s.show);

  if (infoResult.isLoading) {
    return <Spin />;
  }

  if (infoResult.isError || !infoResult.data) {
    return <span>{t("unknown")}</span>;
  }

  const info = infoResult.data;
  const commit_suffix = info.git_commit ? <Text type="secondary">{` (${info.git_commit})`}</Text> : <></>;

  // Subtle "update available" hint (#293): only when the server's daily check found a newer
  // release. Clicking it opens the per-install-type update dialog (#294) — a real update button
  // on native installs, tailored instructions elsewhere, plus the release-notes link.
  const updateHint = info.update_available ? (
    <Tooltip title={info.latest_version ? t("update.tooltip", { version: info.latest_version }) : undefined}>
      <Button type="link" size="small" onClick={showUpdateModal} style={{ padding: 0, height: "auto", fontSize: 12 }}>
        {t("update.available")}
      </Button>
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
