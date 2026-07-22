import { useTranslate } from "@refinedev/core";
import { Alert, Button, Modal, Space, Typography, notification } from "antd";
import { useState } from "react";
import { useCurrentUser } from "../utils/auth";
import { triggerUpdate, useUpdateModal } from "../utils/updateAction";
import { useInfo } from "../utils/useInfo";

const { Paragraph, Text, Link } = Typography;

// Per-install-type update action (#294). A single modal, opened from the version hint or the
// update toast, that renders the right thing for how Spoolman was installed:
//   native   -> a real "Update now" button (POST /update runs scripts/update.sh), or, when the
//               action is gated off, the manual shell command;
//   docker   -> `docker compose pull && up -d` plus an image-tag reminder;
//   ha_addon -> a pointer to Home Assistant's own add-on update UI;
//   unknown  -> a generic "reinstall the latest release" note.
// The button is only ever enabled for an admin on a native install whose server-side gate is open
// (update_action_available) — the endpoint enforces the same, this just avoids a pointless 403.

const DOCKER_COMMAND = "docker compose pull && docker compose up -d";
const MANUAL_COMMAND = "bash scripts/update.sh";

export const UpdateModal = () => {
  const t = useTranslate();
  const open = useUpdateModal((s) => s.open);
  const close = useUpdateModal((s) => s.close);
  const { data: info } = useInfo();
  const currentUser = useCurrentUser();
  const isAdmin = currentUser.data?.role !== "readonly";
  const [loading, setLoading] = useState(false);

  if (!info) {
    return null;
  }

  const installType = info.install_type ?? "unknown";

  const runUpdate = async () => {
    setLoading(true);
    try {
      const result = await triggerUpdate();
      notification.success({
        message: t("update.action.started.title"),
        description: result.restart_managed
          ? t("update.action.started.descriptionManaged")
          : t("update.action.started.descriptionManual"),
        duration: 0,
      });
      close();
    } catch (error) {
      notification.error({
        message: t("update.action.failed.title"),
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setLoading(false);
    }
  };

  const releaseNotes = info.release_url ? (
    <Paragraph>
      <Link href={info.release_url} target="_blank" rel="noopener noreferrer">
        {t("update.action.viewReleaseNotes")}
      </Link>
    </Paragraph>
  ) : null;

  let body: React.ReactNode;
  if (installType === "native") {
    if (info.update_action_available && isAdmin) {
      body = (
        <>
          <Paragraph>{t("update.action.native.description")}</Paragraph>
          <Alert type="info" showIcon message={t("update.action.native.restartNotice")} style={{ marginBottom: 12 }} />
          <Button type="primary" loading={loading} onClick={runUpdate}>
            {info.latest_version
              ? t("update.action.updateToVersion", { version: info.latest_version })
              : t("update.action.updateNow")}
          </Button>
        </>
      );
    } else if (info.update_action_available && !isAdmin) {
      body = <Alert type="warning" showIcon message={t("update.action.native.adminRequired")} />;
    } else {
      body = (
        <>
          <Paragraph>{t("update.action.native.disabled")}</Paragraph>
          <Paragraph>
            <Text code copyable={{ text: MANUAL_COMMAND }}>
              {MANUAL_COMMAND}
            </Text>
          </Paragraph>
        </>
      );
    }
  } else if (installType === "docker") {
    body = (
      <>
        <Paragraph>{t("update.action.docker.description")}</Paragraph>
        <Paragraph>
          <Text code copyable={{ text: DOCKER_COMMAND }}>
            {DOCKER_COMMAND}
          </Text>
        </Paragraph>
        <Paragraph type="secondary">
          {t("update.action.docker.tagReminder", { version: info.latest_version ?? "latest" })}
        </Paragraph>
      </>
    );
  } else if (installType === "ha_addon") {
    body = (
      <>
        <Paragraph>{t("update.action.haAddon.description")}</Paragraph>
        <Paragraph>
          <Text strong>{t("update.action.haAddon.steps")}</Text>
        </Paragraph>
      </>
    );
  } else {
    body = <Paragraph>{t("update.action.unknown.description")}</Paragraph>;
  }

  return (
    <Modal
      title={t("update.action.modalTitle")}
      open={open}
      onCancel={close}
      footer={[
        <Button key="close" onClick={close}>
          {t("update.action.close")}
        </Button>,
      ]}
    >
      <Space direction="vertical" style={{ width: "100%" }}>
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          {t("update.action.currentVersion", { version: info.version })}
          {info.latest_version ? ` — ${t("update.action.latestVersion", { version: info.latest_version })}` : ""}
        </Paragraph>
        {body}
        {releaseNotes}
      </Space>
    </Modal>
  );
};
