import { useTranslate } from "@refinedev/core";
import { useQuery } from "@tanstack/react-query";
import { Button, Input, Modal, Popconfirm, Select, Space, Table, Typography, message } from "antd";
import { useState } from "react";
import { getApiToken } from "../../utils/apiToken";
import { type Role, type User, createUser, deleteUser, listUsers, logout, updateUser } from "../../utils/auth";

const { Title, Paragraph, Text } = Typography;

const ROLE_OPTIONS = (t: (key: string) => string) => [
  { value: "admin", label: t("auth.roles.admin") },
  { value: "readonly", label: t("auth.roles.readonly") },
];

/**
 * Admin-only account management (#52): create/list users, change roles, reset passwords, delete, and
 * log out. The backend forbids removing the last admin, so the UI just surfaces its errors. Shown as
 * a settings tab; it is hidden from readonly users in the settings nav.
 */
export function UsersSettings() {
  const t = useTranslate();
  const [messageApi, contextHolder] = message.useMessage();
  const usersQuery = useQuery<User[]>({ queryKey: ["auth", "users"], queryFn: listUsers });
  const users = usersQuery.data ?? [];

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("admin");
  const [creating, setCreating] = useState(false);
  const [resetTarget, setResetTarget] = useState<User | null>(null);
  const [resetPassword, setResetPassword] = useState("");

  const roleOptions = ROLE_OPTIONS(t);
  const fail = (e: unknown) => messageApi.error(e instanceof Error ? e.message : String(e));

  const onCreate = async () => {
    if (!username.trim() || !password) {
      messageApi.warning(t("auth.users.need_fields"));
      return;
    }
    setCreating(true);
    try {
      await createUser(username.trim(), password, role);
      messageApi.success(t("auth.users.created", { username: username.trim() }));
      setUsername("");
      setPassword("");
      usersQuery.refetch();
    } catch (e) {
      fail(e);
    } finally {
      setCreating(false);
    }
  };

  const onChangeRole = async (user: User, newRole: Role) => {
    try {
      await updateUser(user.id, { role: newRole });
      usersQuery.refetch();
    } catch (e) {
      fail(e);
    }
  };

  const onDelete = async (user: User) => {
    try {
      await deleteUser(user.id);
      usersQuery.refetch();
    } catch (e) {
      fail(e);
    }
  };

  const onResetPassword = async () => {
    if (!resetTarget || !resetPassword) return;
    try {
      await updateUser(resetTarget.id, { password: resetPassword });
      messageApi.success(t("auth.users.password_reset"));
      setResetTarget(null);
      setResetPassword("");
    } catch (e) {
      fail(e);
    }
  };

  return (
    <>
      {contextHolder}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <Title level={4}>{t("auth.users.title")}</Title>
        {getApiToken() && <Button onClick={logout}>{t("auth.logout")}</Button>}
      </div>
      <Paragraph type="secondary">{t("auth.users.help")}</Paragraph>

      <Space wrap style={{ marginBottom: 16 }}>
        <Input
          placeholder={t("auth.login.username")}
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          style={{ width: 160 }}
        />
        <Input.Password
          placeholder={t("auth.login.password")}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={{ width: 160 }}
        />
        <Select<Role> value={role} onChange={setRole} options={roleOptions} style={{ width: 140 }} />
        <Button type="primary" loading={creating} onClick={onCreate}>
          {t("auth.users.add")}
        </Button>
      </Space>

      <Table<User>
        rowKey="id"
        size="small"
        loading={usersQuery.isLoading}
        dataSource={users}
        pagination={false}
        columns={[
          { title: t("auth.login.username"), dataIndex: "username" },
          {
            title: t("auth.users.role"),
            dataIndex: "role",
            render: (value: Role, record) => (
              <Select<Role>
                value={value}
                options={roleOptions}
                style={{ width: 140 }}
                onChange={(newRole) => onChangeRole(record, newRole)}
              />
            ),
          },
          {
            title: "",
            key: "actions",
            align: "right",
            render: (_, record) => (
              <Space>
                <Button size="small" onClick={() => setResetTarget(record)}>
                  {t("auth.users.reset_password")}
                </Button>
                <Popconfirm title={t("auth.users.delete_confirm")} onConfirm={() => onDelete(record)}>
                  <Button size="small" danger>
                    {t("buttons.delete")}
                  </Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />

      <Modal
        open={resetTarget !== null}
        title={t("auth.users.reset_password_for", { username: resetTarget?.username ?? "" })}
        okText={t("auth.users.reset_password")}
        cancelText={t("buttons.cancel")}
        onOk={onResetPassword}
        onCancel={() => {
          setResetTarget(null);
          setResetPassword("");
        }}
        destroyOnClose
      >
        <Text type="secondary">{t("auth.users.reset_password_help")}</Text>
        <Input.Password
          autoFocus
          style={{ marginTop: 8 }}
          value={resetPassword}
          onChange={(e) => setResetPassword(e.target.value)}
          onPressEnter={onResetPassword}
        />
      </Modal>
    </>
  );
}

export default UsersSettings;
