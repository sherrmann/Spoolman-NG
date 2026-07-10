import { Form, Input, Modal, Typography } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { setApiToken, useApiTokenModal } from "../utils/apiToken";
import { fetchAuthStatus, login } from "../utils/auth";

/**
 * Credential prompt shown when the API answers 401 with WWW-Authenticate: Bearer. When user accounts
 * are enabled (#52) it is a username/password login form; otherwise it falls back to the raw
 * machine-token entry (#48). Either way the credential is stored via the shared apiToken seam and the
 * page reloads so it is applied to every transport (axios/fetch/websocket) and the data refetches.
 */
export function ApiTokenModal() {
  const { t } = useTranslation();
  const open = useApiTokenModal((s) => s.open);
  const close = useApiTokenModal((s) => s.close);

  const [accountsEnabled, setAccountsEnabled] = useState(false);
  const [token, setToken] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setError(null);
    fetchAuthStatus()
      .then((status) => setAccountsEnabled(status.accounts_enabled))
      .catch(() => setAccountsEnabled(false));
  }, [open]);

  const submitToken = () => {
    const value = token.trim();
    if (!value) return;
    setApiToken(value);
    close();
    window.location.reload();
  };

  const submitLogin = async () => {
    if (!username.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await login(username.trim(), password);
      close();
      window.location.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSubmitting(false);
    }
  };

  if (accountsEnabled) {
    return (
      <Modal
        open={open}
        title={t("auth.login.title")}
        okText={t("auth.login.submit")}
        cancelText={t("buttons.cancel")}
        confirmLoading={submitting}
        onOk={submitLogin}
        onCancel={close}
        destroyOnClose
      >
        <Form layout="vertical">
          <Form.Item label={t("auth.login.username")}>
            <Input autoFocus value={username} onChange={(e) => setUsername(e.target.value)} />
          </Form.Item>
          <Form.Item label={t("auth.login.password")}>
            <Input.Password value={password} onChange={(e) => setPassword(e.target.value)} onPressEnter={submitLogin} />
          </Form.Item>
          {error && <Typography.Text type="danger">{error}</Typography.Text>}
        </Form>
      </Modal>
    );
  }

  return (
    <Modal
      open={open}
      title={t("apiToken.title")}
      okText={t("apiToken.submit")}
      cancelText={t("buttons.cancel")}
      onOk={submitToken}
      onCancel={close}
      destroyOnClose
    >
      <Typography.Paragraph type="secondary">{t("apiToken.help")}</Typography.Paragraph>
      <Input.Password
        autoFocus
        value={token}
        placeholder={t("apiToken.placeholder")}
        onChange={(e) => setToken(e.target.value)}
        onPressEnter={submitToken}
      />
    </Modal>
  );
}
