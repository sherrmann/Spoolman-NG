import {
  AppstoreOutlined,
  DesktopOutlined,
  DownOutlined,
  MoonOutlined,
  RocketOutlined,
  SunOutlined,
} from "@ant-design/icons";
import type { RefineThemedLayoutHeaderProps } from "@refinedev/antd";
import { useGetLocale, useSetLocale, useTranslate } from "@refinedev/core";
import {
  Grid,
  Layout as AntdLayout,
  Button,
  Dropdown,
  MenuProps,
  Segmented,
  Space,
  Tooltip,
  message,
  theme,
} from "antd";
import React, { useContext } from "react";
import { ColorModeContext, ThemePreference } from "../../contexts/color-mode";
import { getBasePath } from "../../utils/url";
import { UiClient, shouldShowUiClientSwitch, switchUiClient } from "../../utils/uiClient";
import { useInfo } from "../../utils/useInfo";
import { Version } from "../version";

import { languages } from "../../i18n";
import { ChatDrawer } from "../chatDrawer";
import ScanModal from "../scanModal";
import { UpdateModal } from "../updateModal";
import { UpdateNotification } from "../updateNotification";

const { useToken } = theme;

export const Header = ({ sticky }: RefineThemedLayoutHeaderProps) => {
  const { token } = useToken();
  const locale = useGetLocale();
  const changeLanguage = useSetLocale();
  const { preference, setPreference } = useContext(ColorModeContext);
  const t = useTranslate();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;
  const infoResult = useInfo();
  const [messageApi, messageContextHolder] = message.useMessage();

  const currentLocale = locale();

  const themeOptions = [
    { value: "system", icon: <DesktopOutlined />, title: t("theme.system") },
    { value: "light", icon: <SunOutlined />, title: t("theme.light") },
    { value: "dark", icon: <MoonOutlined />, title: t("theme.dark") },
  ];

  // Shown only when the backend opted in and both bundles are built (shouldShowUiClientSwitch);
  // absent/loading /info renders nothing. On mobile there isn't room for two text labels next to
  // the language dropdown and the theme control, so it collapses to icon + hover title — the same
  // compact shape the theme Segmented already uses on every breakpoint.
  const showUiClientSwitch = shouldShowUiClientSwitch(infoResult.data);
  const uiClientOptionMeta: { value: UiClient; label: string; icon: React.ReactNode }[] = [
    { value: "react", label: t("ui_version.classic"), icon: <AppstoreOutlined /> },
    { value: "svelte", label: t("ui_version.new"), icon: <RocketOutlined /> },
  ];
  const uiClientOptions = uiClientOptionMeta.map(({ value, label, icon }) =>
    isMobile ? { value, icon, title: label } : { value, label },
  );

  const handleUiClientChange = (value: string | number) => {
    const target = value as UiClient;
    // Only the svelte switch has an async gap (unregistering service workers) before the
    // reload fires — the react switch reloads right away, so no feedback is needed for it.
    if (target === "svelte") {
      void messageApi.loading({ content: t("ui_version.switching"), key: "ui-client-switch", duration: 0 });
    }
    void switchUiClient(target);
  };

  const menuItems: MenuProps["items"] = [...(Object.keys(languages) || [])].sort().map((lang: string) => ({
    key: lang,
    onClick: () => changeLanguage(lang),
    label: languages[lang].name,
  }));

  const headerStyles: React.CSSProperties = {
    backgroundColor: token.colorBgElevated,
    display: "flex",
    justifyContent: "flex-end",
    alignItems: "center",
    padding: "0px 24px",
    height: "64px",
  };

  if (sticky) {
    headerStyles.position = "sticky";
    headerStyles.top = 0;
    headerStyles.zIndex = 1;
  }

  return (
    <AntdLayout.Header style={headerStyles}>
      {messageContextHolder}
      <UpdateNotification />
      <UpdateModal />
      <Space size="small" style={{ marginRight: "auto", opacity: 0.85, fontSize: 12, marginLeft: isMobile ? 48 : 0 }}>
        {isMobile ? (
          <Version />
        ) : (
          <span>
            {t("version")} <Version />
          </span>
        )}
        <Button
          icon={<img src={getBasePath() + "/kofi_s_logo_nolabel.png"} alt="" aria-hidden style={{ height: "1.4em" }} />}
          type="text"
          size="small"
          href="https://ko-fi.com/sherrmann"
          target="_blank"
          rel="noopener noreferrer"
          style={{ fontSize: 12, opacity: 0.7, padding: "0 4px" }}
        >
          {!isMobile && t("kofi")}
        </Button>
      </Space>
      <Space>
        <Dropdown
          menu={{
            items: menuItems,
            selectedKeys: currentLocale ? [currentLocale] : [],
          }}
        >
          <Button type="text">
            <Space>
              {languages[currentLocale ?? "en"].name}
              <DownOutlined />
            </Space>
          </Button>
        </Dropdown>
        <Segmented
          aria-label={t("theme.label")}
          options={themeOptions}
          value={preference}
          onChange={(value) => setPreference(value as ThemePreference)}
        />
        {showUiClientSwitch && (
          <Tooltip title={t("ui_version.tooltip")}>
            <Segmented
              aria-label={t("ui_version.label")}
              options={uiClientOptions}
              value={infoResult.data?.client_active as UiClient | undefined}
              onChange={handleUiClientChange}
            />
          </Tooltip>
        )}
        <ScanModal />
        <ChatDrawer />
      </Space>
    </AntdLayout.Header>
  );
};
