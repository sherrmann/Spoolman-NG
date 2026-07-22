import { useTranslate } from "@refinedev/core";
import { Alert, Button, Card, Space, Spin, Typography } from "antd";
import { useEffect, useState } from "react";
import { useCurrentUser } from "../../utils/auth";

export interface UpdateInfo {
  install_type: string;
  update_available: boolean;
  latest_version: string | null;
  can_update: boolean;
  update_button_enabled: boolean;
  instructions: string | null;
}

const { Text, Title } = Typography;

interface UpdateStatus {
  status: string;
  message: string;
  instructions: string | null;
}

export function UpdateSettings() {
  const t = useTranslate();
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [updateStatus, setUpdateStatus] = useState<UpdateStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const currentUser = useCurrentUser();

  const fetchUpdateInfo = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/v1/update/info");
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data: UpdateInfo = await response.json();
      setUpdateInfo(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch update info");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUpdateInfo();
  }, []);

  const handleUpdate = async () => {
    if (!updateInfo?.update_button_enabled) return;

    setUpdating(true);
    setError(null);
    setUpdateStatus(null);

    try {
      const response = await fetch("/api/v1/update", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: "Unknown error" }));
        throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }

      const data: UpdateStatus = await response.json();
      setUpdateStatus(data);
      
      // Refresh the update info after a short delay
      setTimeout(() => {
        fetchUpdateInfo();
      }, 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to trigger update");
    } finally {
      setUpdating(false);
    }
  };

  const getInstallTypeLabel = (installType: string) => {
    switch (installType) {
      case "native":
        return t("settings.update.install_type.native");
      case "docker":
        return t("settings.update.install_type.docker");
      case "ha_addon":
        return t("settings.update.install_type.ha_addon");
      default:
        return t("settings.update.install_type.unknown");
    }
  };

  const isAdmin = currentUser.data?.role !== "readonly";

  if (loading) {
    return (
      <Spin size="large" style={{ display: "flex", justifyContent: "center", padding: 24 }} />
    );
  }

  if (error) {
    return (
      <Alert
        message={t("settings.update.error_title")}
        description={error}
        type="error"
        showIcon
      />
    );
  }

  if (!updateInfo) {
    return (
      <Alert
        message={t("settings.update.unavailable_title")}
        description={t("settings.update.unavailable_description")}
        type="info"
        showIcon
      />
    );
  }

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card>
        <Title level={4}>{t("settings.update.title")}</Title>
        
        <Space direction="vertical" size="small">
          <Text strong>{t("settings.update.install_type.label")}: </Text>
          <Text>{getInstallTypeLabel(updateInfo.install_type)}</Text>
        </Space>

        <Space direction="vertical" size="small" style={{ marginTop: 16 }}>
          <Text strong>{t("settings.update.current_version.label")}: </Text>
          <Text>{t("settings.update.current_version.value")}</Text>
        </Space>

        {updateInfo.latest_version && (
          <Space direction="vertical" size="small" style={{ marginTop: 16 }}>
            <Text strong>{t("settings.update.latest_version.label")}: </Text>
            <Text>{updateInfo.latest_version}</Text>
          </Space>
        )}

        {updateInfo.update_available && (
          <Alert
            message={t("settings.update.available")}
            type="info"
            showIcon
            style={{ marginTop: 16 }}
          />
        )}

        {updateInfo.install_type === "native" && updateInfo.update_available && (
          <Space direction="vertical" size="middle" style={{ marginTop: 16 }}>
            {updateInfo.update_button_enabled ? (
              <>
                <Button
                  type="primary"
                  onClick={handleUpdate}
                  loading={updating}
                  disabled={!isAdmin}
                >
                  {t("settings.update.update_button")}
                </Button>
                {!isAdmin && (
                  <Text type="secondary">
                    {t("settings.update.admin_required")}
                  </Text>
                )}
              </>
            ) : (
              <Alert
                message={t("settings.update.button_disabled.title")}
                description={t("settings.update.button_disabled.description")}
                type="warning"
                showIcon
              />
            )}
          </Space>
        )}

        {updateInfo.install_type !== "native" && updateInfo.instructions && (
          <Space direction="vertical" size="middle" style={{ marginTop: 16 }}>
            <Text strong>{t("settings.update.instructions.label")}:</Text>
            <Alert
              message={updateInfo.instructions}
              type="info"
              showIcon
            />
          </Space>
        )}

        {updateStatus && (
          <Alert
            message={updateStatus.message}
            description={updateStatus.instructions}
            type={updateStatus.status === "started" ? "success" : "info"}
            showIcon
            style={{ marginTop: 16 }}
          />
        )}
      </Card>
    </Space>
  );
}
