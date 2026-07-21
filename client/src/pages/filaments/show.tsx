import { DATE_TIME_FORMAT } from "../../utils/dateFormat";
import { DateField, NumberField, Show, TextField } from "@refinedev/antd";
import { useShow, useTranslate } from "@refinedev/core";
import { DownOutlined, ExportOutlined, IdcardOutlined, PrinterOutlined, ToolOutlined } from "@ant-design/icons";
import { CalibrationSection } from "../calibration/CalibrationSection";
import { Button, Descriptions, Dropdown, Image, Space, Tabs, Typography, message } from "antd";
import type { MenuProps } from "antd";
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { filamentImageUrl, useEntityImage } from "../../components/entityImage";
import { ExtraFieldDisplay } from "../../components/extraFields";
import SwatchDownloadModal from "../../components/swatchDownloadModal";
import { NumberFieldUnit } from "../../components/numberField";
import SpoolIcon from "../../components/spoolIcon";
import { downloadSlicerProfile, type SlicerFormat } from "../../utils/importExport";
import { enrichText } from "../../utils/parsing";
import { EntityType, useGetFields } from "../../utils/queryFields";
import { useCurrencyFormatter, useUnitScaling } from "../../utils/settings";
import { IFilament } from "./model";
dayjs.extend(utc);

const { Title } = Typography;

export const FilamentShow = () => {
  const t = useTranslate();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const extraFields = useGetFields(EntityType.filament);
  const currencyFormatter = useCurrencyFormatter();
  const unitScaling = useUnitScaling();
  const { query } = useShow<IFilament>({
    liveMode: "auto",
  });
  const { data, isLoading } = query;

  const record = data?.data;

  const [swatchOpen, setSwatchOpen] = useState(false);
  const [messageApi, contextHolder] = message.useMessage();

  // Reference photo (#88): fetched with auth headers into an object URL; null when there is none.
  const photoSrc = useEntityImage(record?.has_image && record.id ? filamentImageUrl(record.id) : null);

  const downloadSlicer = async (slicer: SlicerFormat) => {
    if (!record?.id) return;
    try {
      await downloadSlicerProfile(record.id, slicer);
    } catch (e) {
      messageApi.error(e instanceof Error ? e.message : String(e));
    }
  };

  const formatTitle = (item: IFilament) => {
    let vendorPrefix = "";
    if (item.vendor) {
      vendorPrefix = `${item.vendor.name} - `;
    }
    return t("filament.titles.show_title", {
      id: item.id,
      name: vendorPrefix + item.name,
      interpolation: { escapeValue: false },
    });
  };

  const gotoVendor = (): undefined => {
    const URL = `/vendor/show/${record?.vendor?.id}`;
    navigate(URL);
  };

  const gotoSpools = (): undefined => {
    const URL = `/spool#filters=[{"field":"filament.id","operator":"in","value":[${record?.id}]}]`;
    navigate(URL);
  };

  const colorObj = record?.multi_color_hexes
    ? {
        colors: record.multi_color_hexes.split(","),
        vertical: record.multi_color_direction === "longitudinal",
      }
    : record?.color_hex;

  // "Export" overflow menu — folds the niche label/swatch exports behind a single
  // default-emphasis menu-button rather than emphasizing them as orange primaries.
  const exportMenuItems: MenuProps["items"] = [
    {
      key: "print-labels",
      icon: <PrinterOutlined />,
      label: t("printing.qrcode.button"),
      onClick: () => {
        if (!record?.id) return;
        navigate(`/filament/print?filaments=${record.id}&return=${encodeURIComponent(window.location.pathname)}`);
      },
    },
    {
      key: "download-swatch",
      icon: <IdcardOutlined />,
      label: t("filament.buttons.download_swatch"),
      onClick: () => setSwatchOpen(true),
    },
    {
      key: "slicer-profile",
      icon: <ToolOutlined />,
      label: t("filament.buttons.download_slicer"),
      // #76: generate a native slicer filament profile from this filament's fields.
      children: [
        { key: "slicer-prusa", label: "PrusaSlicer / SuperSlicer", onClick: () => downloadSlicer("prusa") },
        { key: "slicer-orca", label: "OrcaSlicer / Bambu Studio", onClick: () => downloadSlicer("orca") },
        { key: "slicer-cura", label: "Cura", onClick: () => downloadSlicer("cura") },
      ],
    },
  ];

  const activeTab = searchParams.get("tab") === "calibration" ? "calibration" : "details";

  const detailsContent = (
    <>
      {photoSrc && (
        <div style={{ marginBottom: 16 }}>
          <Image
            src={photoSrc}
            alt={record?.name ?? t("filament.fields.image")}
            style={{ maxWidth: 320, maxHeight: 240, borderRadius: 8, objectFit: "contain" }}
          />
        </div>
      )}
      <Title level={5}>{t("filament.fields.id")}</Title>
      <NumberField value={record?.id ?? ""} />
      <Descriptions column={1} bordered size="small">
        <Descriptions.Item label={t("filament.fields.vendor")}>
          <button
            onClick={gotoVendor}
            style={{ background: "none", border: "none", color: "blue", cursor: "pointer", paddingLeft: 0 }}
          >
            {record ? record.vendor?.name : ""}
          </button>
        </Descriptions.Item>
        <Descriptions.Item label={t("filament.fields.registered")}>
          <DateField
            value={dayjs.utc(record?.registered).local()}
            title={dayjs.utc(record?.registered).local().format()}
            format={DATE_TIME_FORMAT}
          />
        </Descriptions.Item>
        <Descriptions.Item label={t("filament.fields.name")}>
          <TextField value={record?.name} />
        </Descriptions.Item>
        <Descriptions.Item label={t("filament.fields.color_hex")}>
          <Space>
            {colorObj && <SpoolIcon color={colorObj} size="large" no_margin />}
            {record?.color_hex && <TextField value={`#${record?.color_hex}`} />}
          </Space>
        </Descriptions.Item>
        <Descriptions.Item label={t("filament.fields.material")}>
          <TextField value={record?.material} />
        </Descriptions.Item>
        <Descriptions.Item label={t("filament.fields.price")}>
          <TextField value={record?.price ? currencyFormatter.format(record.price) : ""} />
        </Descriptions.Item>
        <Descriptions.Item label={t("filament.fields.density")}>
          <NumberFieldUnit
            value={record?.density ?? ""}
            unit="g/cm³"
            options={{ maximumFractionDigits: 2, minimumFractionDigits: 2 }}
          />
        </Descriptions.Item>
        <Descriptions.Item label={t("filament.fields.diameter")}>
          <NumberFieldUnit
            value={record?.diameter ?? ""}
            unit="mm"
            options={{ maximumFractionDigits: 2, minimumFractionDigits: 2 }}
          />
        </Descriptions.Item>
        <Descriptions.Item label={t("filament.fields.weight")}>
          <NumberFieldUnit
            value={record?.weight ?? ""}
            unit="g"
            autoScale={unitScaling}
            options={{ maximumFractionDigits: 1, minimumFractionDigits: 1 }}
          />
        </Descriptions.Item>
        <Descriptions.Item label={t("filament.fields.spool_count")}>
          <NumberField value={record?.spool_count ?? 0} />
        </Descriptions.Item>
        <Descriptions.Item label={t("filament.fields.remaining_weight")}>
          <NumberFieldUnit
            value={record?.remaining_weight ?? 0}
            unit="g"
            autoScale={unitScaling}
            options={{ maximumFractionDigits: 1, minimumFractionDigits: 1 }}
          />
        </Descriptions.Item>
        <Descriptions.Item label={t("filament.fields.spool_weight")}>
          <NumberFieldUnit
            value={record?.spool_weight ?? ""}
            unit="g"
            autoScale={unitScaling}
            options={{ maximumFractionDigits: 1, minimumFractionDigits: 1 }}
          />
        </Descriptions.Item>
        <Descriptions.Item label={t("filament.fields.low_stock_threshold")}>
          {record?.low_stock_threshold == null ? (
            <TextField value="Not Set" />
          ) : (
            <NumberFieldUnit
              value={record.low_stock_threshold}
              unit="g"
              autoScale={unitScaling}
              options={{ maximumFractionDigits: 1, minimumFractionDigits: 1 }}
            />
          )}
        </Descriptions.Item>
        <Descriptions.Item label={t("filament.fields.reserve_count")}>
          {record?.reserve_count == null ? <TextField value="Not Set" /> : <NumberField value={record.reserve_count} />}
        </Descriptions.Item>
        <Descriptions.Item label={t("filament.fields.settings_extruder_temp")}>
          {!record?.settings_extruder_temp ? (
            <TextField value="Not Set" />
          ) : (
            <NumberFieldUnit value={record?.settings_extruder_temp ?? ""} unit="°C" />
          )}
        </Descriptions.Item>
        {record?.settings_extruder_temp_min != null && record?.settings_extruder_temp_max != null && (
          <Descriptions.Item label={t("filament.fields.settings_extruder_temp_range")}>
            <TextField value={`${record.settings_extruder_temp_min}–${record.settings_extruder_temp_max} °C`} />
          </Descriptions.Item>
        )}
        <Descriptions.Item label={t("filament.fields.settings_bed_temp")}>
          {!record?.settings_bed_temp ? (
            <TextField value="Not Set" />
          ) : (
            <NumberFieldUnit value={record?.settings_bed_temp ?? ""} unit="°C" />
          )}
        </Descriptions.Item>
        {record?.settings_bed_temp_min != null && record?.settings_bed_temp_max != null && (
          <Descriptions.Item label={t("filament.fields.settings_bed_temp_range")}>
            <TextField value={`${record.settings_bed_temp_min}–${record.settings_bed_temp_max} °C`} />
          </Descriptions.Item>
        )}
        {record?.spool_type && (
          <Descriptions.Item label={t("filament.fields.spool_type")}>
            <TextField value={t(`filament.spool_type_options.${record.spool_type}`)} />
          </Descriptions.Item>
        )}
        {record?.finish && (
          <Descriptions.Item label={t("filament.fields.finish")}>
            <TextField value={t(`filament.finish_options.${record.finish}`)} />
          </Descriptions.Item>
        )}
        {record?.pattern && (
          <Descriptions.Item label={t("filament.fields.pattern")}>
            <TextField value={t(`filament.pattern_options.${record.pattern}`)} />
          </Descriptions.Item>
        )}
        {record?.translucent != null && (
          <Descriptions.Item label={t("filament.fields.translucent")}>
            <TextField value={record.translucent ? t("yes") : t("no")} />
          </Descriptions.Item>
        )}
        {record?.glow != null && (
          <Descriptions.Item label={t("filament.fields.glow")}>
            <TextField value={record.glow ? t("yes") : t("no")} />
          </Descriptions.Item>
        )}
        <Descriptions.Item label={t("filament.fields.article_number")}>
          <TextField value={record?.article_number} />
        </Descriptions.Item>
        <Descriptions.Item label={t("filament.fields.external_id")}>
          <TextField value={record?.external_id} />
        </Descriptions.Item>
        <Descriptions.Item label={t("filament.fields.comment")}>
          <TextField value={enrichText(record?.comment)} />
        </Descriptions.Item>
      </Descriptions>
      <Title level={4} style={{ marginTop: 16 }}>
        {t("settings.extra_fields.tab")}
      </Title>
      {extraFields?.data?.map((field, index) => (
        <ExtraFieldDisplay key={index} field={field} value={record?.extra[field.key]} />
      ))}
    </>
  );

  return (
    <Show
      isLoading={isLoading}
      title={record ? formatTitle(record) : ""}
      headerButtons={({ defaultButtons }) => (
        <>
          <Button onClick={gotoSpools}>{t("filament.fields.spools")}</Button>
          <Dropdown menu={{ items: exportMenuItems }} trigger={["click"]} disabled={!record?.id}>
            <Button icon={<ExportOutlined />}>
              <Space>
                {t("buttons.export")}
                <DownOutlined />
              </Space>
            </Button>
          </Dropdown>
          {defaultButtons}
        </>
      )}
    >
      <Tabs
        activeKey={activeTab}
        onChange={(key) => {
          setSearchParams(
            (prev) => {
              const next = new URLSearchParams(prev);
              if (key === "calibration") {
                next.set("tab", "calibration");
              } else {
                next.delete("tab");
              }
              return next;
            },
            { replace: true },
          );
        }}
        items={[
          {
            key: "details",
            label: t("filament.tabs.details"),
            children: detailsContent,
          },
          {
            key: "calibration",
            label: t("calibration.title"),
            children: <CalibrationSection filamentId={record?.id} />,
          },
        ]}
      />
      {contextHolder}
      <SwatchDownloadModal filament={swatchOpen ? (record ?? null) : null} onClose={() => setSwatchOpen(false)} />
    </Show>
  );
};

export default FilamentShow;
