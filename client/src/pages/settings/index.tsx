import {
  EnvironmentOutlined,
  FileOutlined,
  HighlightOutlined,
  IdcardOutlined,
  ImportOutlined,
  LinkOutlined,
  PrinterOutlined,
  ThunderboltOutlined,
  ToolOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { List } from "@refinedev/antd";
import { useTranslate } from "@refinedev/core";
import { Menu, theme } from "antd";
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import { useLocation, useNavigate } from "react-router";
import { ExtraFieldsSettings } from "./extraFieldsSettings";
import { EntityType } from "../../utils/queryFields";
import { GeneralSettings } from "./generalSettings";
import { CustomLinksSettings } from "./customLinksSettings";
import { ImportExportSettings } from "./importExportSettings";
import { PrinterSettings } from "./printerSettings";
import { SwatchSettings } from "./swatchSettings";
import "./settings.css";

dayjs.extend(utc);

const { useToken } = theme;

const panels: Record<string, React.ReactNode> = {
  general: <GeneralSettings />,
  swatches: <SwatchSettings />,
  "import-export": <ImportExportSettings />,
  printers: <PrinterSettings />,
  "custom-links": (
    <CustomLinksSettings
      settingKey="custom_links"
      descriptionKey="settings.custom_links.sidebar_description"
      urlLabelKey="settings.custom_links.url"
      urlPlaceholder="http://mainsail.local"
    />
  ),
  "spool-links": (
    <CustomLinksSettings
      settingKey="spool_action_links"
      descriptionKey="settings.custom_links.spool_description"
      urlLabelKey="settings.custom_links.url_template"
      urlHelpKey="settings.custom_links.url_template_help"
      urlPlaceholder="http://moonraker.local/server/spoolman/spool_id?id={id}"
    />
  ),
  "extra-spool": <ExtraFieldsSettings entityType={EntityType.spool} />,
  "extra-filament": <ExtraFieldsSettings entityType={EntityType.filament} />,
  "extra-vendor": <ExtraFieldsSettings entityType={EntityType.vendor} />,
  "extra-location": <ExtraFieldsSettings entityType={EntityType.location} />,
  "extra-printer": <ExtraFieldsSettings entityType={EntityType.printer} />,
};

// Map between menu keys and the URL path under /settings.
const keyToPath: Record<string, string> = {
  general: "/settings",
  swatches: "/settings/swatches",
  "import-export": "/settings/import-export",
  printers: "/settings/printers",
  "custom-links": "/settings/custom-links",
  "spool-links": "/settings/spool-links",
  "extra-spool": "/settings/extra/spool",
  "extra-filament": "/settings/extra/filament",
  "extra-vendor": "/settings/extra/vendor",
  "extra-location": "/settings/extra/location",
  "extra-printer": "/settings/extra/printer",
};

const getActiveKey = (pathname: string): string => {
  const sub = pathname.replace(/^\/settings\/?/, "").replace(/\/$/, "");
  if (sub.startsWith("swatches")) return "swatches";
  if (sub.startsWith("import-export")) return "import-export";
  if (sub.startsWith("custom-links")) return "custom-links";
  if (sub.startsWith("spool-links")) return "spool-links";
  if (sub.startsWith("extra/spool")) return "extra-spool";
  if (sub.startsWith("extra/filament")) return "extra-filament";
  if (sub.startsWith("extra/vendor")) return "extra-vendor";
  if (sub.startsWith("extra/location")) return "extra-location";
  if (sub.startsWith("extra/printer")) return "extra-printer";
  if (sub.startsWith("printers")) return "printers";
  return "general";
};

export const Settings = () => {
  const { token } = useToken();
  const t = useTranslate();
  const navigate = useNavigate();
  const location = useLocation();
  const activeKey = getActiveKey(location.pathname);

  return (
    <List headerButtons={() => null}>
      <div
        className="settings-layout"
        style={{
          background: token.colorBgContainer,
          borderRadius: token.borderRadiusLG,
          color: token.colorText,
        }}
      >
        <div className="settings-nav">
          <Menu
            mode="inline"
            selectedKeys={[activeKey]}
            onClick={(e) => navigate(keyToPath[e.key] ?? "/settings")}
            items={[
              {
                key: "general",
                icon: <ToolOutlined />,
                label: t("settings.general.tab"),
              },
              {
                key: "swatches",
                icon: <IdcardOutlined />,
                label: t("settings.swatch.tab"),
              },
              {
                key: "import-export",
                icon: <ImportOutlined />,
                label: t("settings.import_export.tab"),
              },
              {
                key: "printers",
                icon: <PrinterOutlined />,
                label: t("settings.printers.tab"),
              },
              {
                key: "custom-links",
                icon: <LinkOutlined />,
                label: t("settings.custom_links.sidebar_tab"),
              },
              {
                key: "spool-links",
                icon: <ThunderboltOutlined />,
                label: t("settings.custom_links.spool_tab"),
              },
              { type: "divider" },
              {
                key: "extra-spool",
                icon: <FileOutlined />,
                label: `${t("settings.extra_fields.tab")} - ${t("spool.spool")}`,
              },
              {
                key: "extra-filament",
                icon: <HighlightOutlined />,
                label: `${t("settings.extra_fields.tab")} - ${t("filament.filament")}`,
              },
              {
                key: "extra-vendor",
                icon: <UserOutlined />,
                label: `${t("settings.extra_fields.tab")} - ${t("vendor.vendor")}`,
              },
              {
                key: "extra-location",
                icon: <EnvironmentOutlined />,
                label: `${t("settings.extra_fields.tab")} - ${t("locations.location")}`,
              },
              {
                key: "extra-printer",
                icon: <PrinterOutlined />,
                label: `${t("settings.extra_fields.tab")} - ${t("printer.printer")}`,
              },
            ]}
          />
        </div>
        <div className="settings-content">{panels[activeKey]}</div>
      </div>
    </List>
  );
};

export default Settings;
