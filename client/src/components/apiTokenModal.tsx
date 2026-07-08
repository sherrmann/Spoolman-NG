import { Input, Modal, Typography } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { setApiToken, useApiTokenModal } from "../utils/apiToken";

/**
 * Prompt for the API bearer token (issue #48). Shown when the server has SPOOLMAN_API_TOKEN set and
 * a request came back 401 with WWW-Authenticate: Bearer. On submit the token is stored and the page
 * reloads so it is applied to every transport (axios/fetch/websocket) and the data refetches.
 */
export function ApiTokenModal() {
  const { t } = useTranslation();
  const open = useApiTokenModal((s) => s.open);
  const close = useApiTokenModal((s) => s.close);
  const [value, setValue] = useState("");

  const submit = () => {
    const token = value.trim();
    if (!token) return;
    setApiToken(token);
    close();
    window.location.reload();
  };

  return (
    <Modal
      open={open}
      title={t("apiToken.title")}
      okText={t("apiToken.submit")}
      cancelText={t("buttons.cancel")}
      onOk={submit}
      onCancel={close}
      destroyOnClose
    >
      <Typography.Paragraph type="secondary">{t("apiToken.help")}</Typography.Paragraph>
      <Input.Password
        autoFocus
        value={value}
        placeholder={t("apiToken.placeholder")}
        onChange={(e) => setValue(e.target.value)}
        onPressEnter={submit}
      />
    </Modal>
  );
}
