import { DATE_TIME_FORMAT, DATE_TIME_FORMAT_SHORT } from "../../utils/dateFormat";
import {
  DeleteOutlined,
  DownOutlined,
  EnvironmentOutlined,
  InboxOutlined,
  LinkOutlined,
  PrinterOutlined,
  TagsOutlined,
  ToTopOutlined,
  ToolOutlined,
  UndoOutlined,
  UnorderedListOutlined,
  WifiOutlined,
} from "@ant-design/icons";
import { DateField, EditButton, NumberField, RefreshButton, Show, TextField } from "@refinedev/antd";
import { useDelete, useInvalidate, useList, useShow, useTranslate, useUpdate } from "@refinedev/core";
import {
  Button,
  Card,
  Col,
  Descriptions,
  Dropdown,
  Modal,
  Progress,
  message,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { useGetSpoolUsageEvents } from "../../utils/queryUsageEvents";
import type { MenuProps } from "antd";
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import { useState } from "react";
import { useNavigate } from "react-router";
import { ExtraFieldDisplay } from "../../components/extraFields";
import { NumberFieldUnit } from "../../components/numberField";
import SpoolIcon from "../../components/spoolIcon";
import { enrichText, formatWeight } from "../../utils/parsing";
import { getSpoolEffectiveColor } from "../../utils/spoolColor";
import { buildSpoolActionUrl, useSpoolActionLinks } from "../../utils/spoolActionLinks";
import { EntityType, useGetFields } from "../../utils/queryFields";
import { useCurrencyFormatter, useUnitScaling } from "../../utils/settings";
import NfcBindModal from "../../components/nfcBindModal";
import NfcWriteModal from "../../components/nfcWriteModal";
import { IFilament } from "../filaments/model";
import { setSpoolArchived, useSpoolAdjustModal } from "./functions";
import { ISpool } from "./model";
import { measureSeries } from "./weightHistory";
import { WeightHistoryChart } from "./weightHistoryChart";

dayjs.extend(utc);

const { Title } = Typography;
const { confirm } = Modal;

export const SpoolShow = () => {
  const t = useTranslate();
  const navigate = useNavigate();
  const extraFields = useGetFields(EntityType.spool);
  // #83: the filament's own custom fields describe this spool too; show them read-only below the
  // spool's own fields (they are edited on the filament).
  const filamentExtraFields = useGetFields(EntityType.filament);
  const currencyFormatter = useCurrencyFormatter();
  const unitScaling = useUnitScaling();
  const invalidate = useInvalidate();
  // antd message instance for surfacing adjust/archive failures (#227), matching list.tsx.
  const [messageApi, messageContextHolder] = message.useMessage();

  const { query } = useShow<ISpool>({
    liveMode: "auto",
  });
  const { data, isLoading } = query;

  const record = data?.data;

  const usageEvents = useGetSpoolUsageEvents(record?.id);
  // #104: a weight-history trend from measure events (their gross measured_weight). Empty unless the
  // spool has been weighed at least twice.
  const weightSeries = measureSeries(usageEvents.data ?? []);
  const { mutate: updateSpool } = useUpdate();

  // #100: after a QR/NFC scan lands here, show the other (non-archived) spools of the SAME filament
  // so the user can tell at a glance how much of that filament remains across all spools. Reuses the
  // existing `filament.id` spool filter (same one the Filament show page's "Spools" button uses); the
  // section only renders when siblings exist, so single-spool filaments gain no clutter.
  const filamentId = record?.filament.id;
  const { result: siblingSpoolsResult, query: siblingSpoolsQuery } = useList<ISpool>({
    resource: "spool",
    filters: [{ field: "filament.id", operator: "in", value: filamentId !== undefined ? [filamentId] : [] }],
    pagination: { mode: "off" },
    queryOptions: { enabled: filamentId !== undefined },
  });
  const siblingSpools = (siblingSpoolsResult?.data ?? []).filter((s) => s.id !== record?.id);

  // "Reset usage" (#77): zero used_weight and clear the usage dates. The used_weight change is
  // itself logged as an "update" usage event by the backend.
  const resetUsagePopup = () => {
    if (!record) return;
    confirm({
      title: t("buttons.resetUsage"),
      content: t("spool.messages.reset_usage"),
      okText: t("buttons.resetUsage"),
      okType: "danger",
      cancelText: t("buttons.cancel"),
      onOk() {
        updateSpool(
          {
            resource: "spool",
            id: record.id,
            values: { used_weight: 0, first_used: null, last_used: null },
          },
          {
            onSuccess: () => invalidate({ resource: "spool", id: record.id, invalidates: ["detail"] }),
          },
        );
      },
    });
  };

  const spoolPrice = (item?: ISpool) => {
    const price = item?.price ?? item?.filament.price;
    if (price === undefined) {
      return "";
    }
    return currencyFormatter.format(price);
  };

  // NFC state
  const [nfcWriteModalVisible, setNfcWriteModalVisible] = useState(false);
  const [nfcBindModalVisible, setNfcBindModalVisible] = useState(false);
  // Always show the NFC button — the modal handles mode availability,
  // and the "Download Raw Binary" option works without NFC hardware or Web NFC.
  const showNfcButton = true;

  // Provides the function to open the spool adjustment modal and the modal component itself
  const { openSpoolAdjustModal, spoolAdjustModal } = useSpoolAdjustModal(messageApi);

  // User-configured per-spool action links (#140), rendered as a dropdown only when configured.
  const actionLinks = useSpoolActionLinks();

  // Function for opening an ant design modal that asks for confirmation for archiving a spool
  const archiveSpool = async (spool: ISpool, archive: boolean) => {
    try {
      await setSpoolArchived(spool, archive);
    } catch (error) {
      // Surface the failure (#227) - the page would otherwise just silently stay unchanged.
      messageApi.error(error instanceof Error && error.message ? error.message : t("notifications.error"));
      return;
    }
    invalidate({
      resource: "spool",
      id: spool.id,
      invalidates: ["list", "detail"],
    });
  };

  const { mutate: deleteSpool } = useDelete();

  const deleteSpoolPopup = (spool: ISpool | undefined) => {
    if (spool === undefined) {
      return;
    }
    confirm({
      title: t("buttons.confirm"),
      okText: t("buttons.delete"),
      okType: "danger",
      cancelText: t("buttons.cancel"),
      onOk() {
        return new Promise<void>((resolve, reject) => {
          deleteSpool(
            { resource: "spool", id: spool.id },
            {
              onSuccess: () => {
                resolve();
                navigate("/spool");
              },
              onError: (error) => reject(error),
            },
          );
        });
      },
    });
  };

  const archiveSpoolPopup = async (spool: ISpool | undefined) => {
    if (spool === undefined) {
      return;
    }
    // If the spool has no remaining weight, archive it immediately since it's likely not a mistake
    if (spool.remaining_weight != undefined && spool.remaining_weight <= 0) {
      await archiveSpool(spool, true);
    } else {
      confirm({
        title: t("spool.titles.archive"),
        content: t("spool.messages.archive"),
        okText: t("buttons.archive"),
        okType: "primary",
        cancelText: t("buttons.cancel"),
        onOk() {
          return archiveSpool(spool, true);
        },
      });
    }
  };

  const formatFilament = (item: IFilament) => {
    let vendorPrefix = "";
    if (item.vendor) {
      vendorPrefix = `${item.vendor.name} - `;
    }
    let name = item.name;
    if (!name) {
      name = `ID: ${item.id}`;
    }
    let material = "";
    if (item.material) {
      material = ` - ${item.material}`;
    }
    return `${vendorPrefix}${name}${material}`;
  };

  const filamentURL = (item: IFilament) => {
    const URL = `/filament/show/${item.id}`;
    return <a href={URL}>{formatFilament(item)}</a>;
  };

  const formatTitle = (item: ISpool) => {
    return t("spool.titles.show_title", {
      id: item.id,
      name: formatFilament(item.filament),
      interpolation: { escapeValue: false },
    });
  };

  // #74: the spool's own color override wins, else the filament color.
  const colorObj = record ? getSpoolEffectiveColor(record) : undefined;

  // Remaining-stock share for the hero card's progress bar; undefined (bar hidden) when the
  // spool carries no usable total. Mirrors the dashboard's remaining→initial→filament chain.
  const heroTotal = record?.initial_weight ?? record?.filament.weight;
  const heroRemaining = record?.remaining_weight;
  const remainingPct =
    heroTotal && heroRemaining != null ? Math.max(0, Math.min(100, (heroRemaining / heroTotal) * 100)) : undefined;
  // Progress accepts one colour; for multi-colour filament use the first as the accent.
  const progressColor = typeof colorObj === "string" ? "#" + colorObj.replace("#", "") : colorObj?.colors?.[0];

  // "All spools of this filament": jump to the spool list pre-filtered to this filament, via
  // the same URL-hash mechanism shared table links use (read by useInitialTableState).
  const goToSiblingSpools = () => {
    if (filamentId === undefined) return;
    const params = new URLSearchParams();
    params.set("filters", JSON.stringify([{ field: "filament.id", operator: "in", value: [filamentId] }]));
    navigate(`/spool#${params.toString()}`);
  };

  // "Labels & Tags" overflow menu — folds the niche label/NFC actions behind a single
  // default-emphasis menu-button, leaving "Adjust Spool Filament" as the only primary.
  const labelsMenuItems: MenuProps["items"] = [
    {
      key: "print-labels",
      icon: <PrinterOutlined />,
      label: t("printing.qrcode.button"),
      onClick: () => {
        if (!record) return;
        navigate(`/spool/print?spools=${record.id}&return=${encodeURIComponent(window.location.pathname)}`);
      },
    },
    // NFC entries are gated so the menu (and printing) survives if the flag ever becomes conditional.
    ...(showNfcButton
      ? [
          {
            key: "link-nfc",
            icon: <LinkOutlined />,
            label: t("nfc.bind_button"),
            onClick: () => setNfcBindModalVisible(true),
          },
          {
            key: "encode-nfc",
            icon: <WifiOutlined />,
            label: t("nfc.encode_button"),
            onClick: () => setNfcWriteModalVisible(true),
          },
        ]
      : []),
  ];

  return (
    <Show
      isLoading={isLoading}
      canDelete={false}
      title={record ? formatTitle(record) : ""}
      headerButtons={({ editButtonProps, refreshButtonProps }) => (
        <>
          <Button type="primary" icon={<ToolOutlined />} onClick={() => record && openSpoolAdjustModal(record)}>
            {t("spool.titles.adjust")}
          </Button>
          <Dropdown menu={{ items: labelsMenuItems }} trigger={["click"]} disabled={!record}>
            <Button icon={<TagsOutlined />}>
              <Space>
                {t("buttons.labelsAndTags")}
                <DownOutlined />
              </Space>
            </Button>
          </Dropdown>
          {actionLinks.length > 0 && (
            <Dropdown
              trigger={["click"]}
              disabled={!record}
              menu={{
                items: actionLinks.map((link, index) => ({
                  key: `action-link-${index}`,
                  icon: <LinkOutlined />,
                  label: link.name,
                  onClick: () =>
                    record && window.open(buildSpoolActionUrl(link.url, record), "_blank", "noopener,noreferrer"),
                })),
              }}
            >
              <Button icon={<LinkOutlined />}>
                <Space>
                  {t("spool.custom_actions")}
                  <DownOutlined />
                </Space>
              </Button>
            </Dropdown>
          )}
          {/* Archive is the safe, primary retirement path; Delete rides in its overflow. */}
          <Dropdown.Button
            danger={!record?.archived}
            trigger={["click"]}
            disabled={!record}
            onClick={() => (record?.archived ? archiveSpool(record, false) : archiveSpoolPopup(record))}
            menu={{
              items: [
                {
                  key: "reset-usage",
                  icon: <UndoOutlined />,
                  label: t("buttons.resetUsage"),
                  onClick: () => resetUsagePopup(),
                },
                {
                  key: "delete",
                  icon: <DeleteOutlined />,
                  label: t("buttons.delete"),
                  danger: true,
                  onClick: () => deleteSpoolPopup(record),
                },
              ],
            }}
          >
            {record?.archived ? <ToTopOutlined /> : <InboxOutlined />}
            {record?.archived ? t("buttons.unArchive") : t("buttons.archive")}
          </Dropdown.Button>

          {/* Replaces the stock "Spools" list button: jumping to the *sibling* spools of this
              filament is the navigation people actually want from here. */}
          <Tooltip title={t("spool.sibling_spools.tooltip")}>
            <Button icon={<UnorderedListOutlined />} disabled={!record} onClick={goToSiblingSpools}>
              {t("spool.sibling_spools.button")}
            </Button>
          </Tooltip>
          {editButtonProps && <EditButton {...editButtonProps} />}
          {refreshButtonProps && <RefreshButton {...refreshButtonProps} />}
          {messageContextHolder}
          {spoolAdjustModal}
          <NfcBindModal
            spool={record}
            visible={nfcBindModalVisible}
            onClose={() => setNfcBindModalVisible(false)}
            onBound={() => invalidate({ resource: "spool", id: record?.id, invalidates: ["detail"] })}
          />
          <NfcWriteModal spool={record} visible={nfcWriteModalVisible} onClose={() => setNfcWriteModalVisible(false)} />
        </>
      )}
    >
      {/* Hero summary: swatch, identity tags, stock bar and the key numbers at a glance;
          the full field-by-field record stays in the table below. */}
      {record && (
        <Card style={{ marginBottom: 16 }}>
          <Row gutter={[24, 16]} align="middle" wrap>
            <Col flex="none">
              <SpoolIcon color={colorObj} size="large" no_margin />
            </Col>
            <Col flex="auto" style={{ minWidth: 220 }}>
              <Typography.Title level={4} style={{ marginTop: 0, marginBottom: 8 }}>
                {filamentURL(record.filament)}
              </Typography.Title>
              <Space size={[4, 4]} wrap>
                {record.filament.material && <Tag color="blue">{record.filament.material}</Tag>}
                {record.location && <Tag icon={<EnvironmentOutlined />}>{record.location}</Tag>}
                {record.lot_nr && (
                  <Tag>
                    {t("spool.fields.lot_nr")}: {record.lot_nr}
                  </Tag>
                )}
                {record.printer && <Tag icon={<PrinterOutlined />}>{record.printer.name}</Tag>}
                {record.archived && <Tag color="red">{t("spool.fields.archived")}</Tag>}
              </Space>
              {remainingPct !== undefined && (
                <div style={{ maxWidth: 420, marginTop: 12 }}>
                  <Progress
                    percent={remainingPct}
                    strokeColor={progressColor}
                    format={(pct) => `${Math.round(pct ?? 0)}%`}
                    status="normal"
                  />
                </div>
              )}
            </Col>
            <Col flex="none">
              <Space size="large" wrap>
                <Statistic
                  title={t("spool.fields.remaining_weight")}
                  value={record.remaining_weight != null ? formatWeight(record.remaining_weight) : "-"}
                />
                <Statistic
                  title={t("spool.fields.used_weight")}
                  value={record.used_weight != null ? formatWeight(record.used_weight) : "-"}
                />
                <Statistic title={t("spool.fields.price")} value={spoolPrice(record) || "-"} />
              </Space>
            </Col>
          </Row>
        </Card>
      )}
      <Descriptions column={1} bordered size="small">
        <Descriptions.Item label={t("spool.fields.id")}>
          <NumberField value={record?.id ?? ""} />
        </Descriptions.Item>
        <Descriptions.Item label={t("spool.fields.filament")}>
          <Space>
            {colorObj && <SpoolIcon color={colorObj} size="large" no_margin />}
            <TextField value={record ? filamentURL(record?.filament) : ""} />
          </Space>
        </Descriptions.Item>
        <Descriptions.Item label={t("spool.fields.price")}>
          <TextField value={spoolPrice(record)} />
        </Descriptions.Item>
        <Descriptions.Item label={t("spool.fields.registered")}>
          <DateField
            value={dayjs.utc(record?.registered).local()}
            title={dayjs.utc(record?.registered).local().format()}
            format={DATE_TIME_FORMAT}
          />
        </Descriptions.Item>
        <Descriptions.Item label={t("spool.fields.first_used")}>
          <DateField
            hidden={!record?.first_used}
            value={dayjs.utc(record?.first_used).local()}
            title={dayjs.utc(record?.first_used).local().format()}
            format={DATE_TIME_FORMAT}
          />
        </Descriptions.Item>
        <Descriptions.Item label={t("spool.fields.last_used")}>
          <DateField
            hidden={!record?.last_used}
            value={dayjs.utc(record?.last_used).local()}
            title={dayjs.utc(record?.last_used).local().format()}
            format={DATE_TIME_FORMAT}
          />
        </Descriptions.Item>
        <Descriptions.Item label={t("spool.fields.remaining_length")}>
          <NumberFieldUnit
            value={record?.remaining_length ?? ""}
            unit="mm"
            autoScale={unitScaling}
            options={{ maximumFractionDigits: 1, minimumFractionDigits: 1 }}
          />
        </Descriptions.Item>
        <Descriptions.Item label={t("spool.fields.used_length")}>
          <NumberFieldUnit
            value={record?.used_length ?? ""}
            unit="mm"
            autoScale={unitScaling}
            options={{ maximumFractionDigits: 1, minimumFractionDigits: 1 }}
          />
        </Descriptions.Item>
        <Descriptions.Item label={t("spool.fields.remaining_weight")}>
          <NumberFieldUnit
            value={record?.remaining_weight ?? ""}
            unit="g"
            autoScale={unitScaling}
            options={{ maximumFractionDigits: 1, minimumFractionDigits: 1 }}
          />
        </Descriptions.Item>
        <Descriptions.Item label={t("spool.fields.used_weight")}>
          <NumberFieldUnit
            value={record?.used_weight ?? ""}
            unit="g"
            autoScale={unitScaling}
            options={{ maximumFractionDigits: 1, minimumFractionDigits: 1 }}
          />
        </Descriptions.Item>
        <Descriptions.Item label={t("spool.fields.location")}>
          <TextField value={record?.location} />
        </Descriptions.Item>
        {record?.printer && (
          <Descriptions.Item label={t("spool.fields.printer")}>
            <TextField value={record.printer.name} />
          </Descriptions.Item>
        )}
        <Descriptions.Item label={t("spool.fields.lot_nr")}>
          <TextField value={record?.lot_nr} />
        </Descriptions.Item>
        <Descriptions.Item label={t("spool.fields.comment")}>
          <TextField value={enrichText(record?.comment)} />
        </Descriptions.Item>
        <Descriptions.Item label={t("spool.fields.archived")}>
          <TextField value={record?.archived ? t("yes") : t("no")} />
        </Descriptions.Item>
      </Descriptions>
      <Title level={4} style={{ marginTop: 16 }}>
        {t("settings.extra_fields.tab")}
      </Title>
      {extraFields?.data?.map((field, index) => (
        <ExtraFieldDisplay key={index} field={field} value={record?.extra[field.key]} />
      ))}
      {filamentExtraFields?.data && filamentExtraFields.data.length > 0 && (
        <>
          <Title level={4}>{t("spool.filament_extra_fields")}</Title>
          {filamentExtraFields.data.map((field, index) => (
            <ExtraFieldDisplay key={index} field={field} value={record?.filament.extra?.[field.key]} />
          ))}
        </>
      )}
      {siblingSpools.length > 0 && (
        <>
          <Title level={4}>{t("spool.sibling_spools.title")}</Title>
          <Table
            size="small"
            rowKey="id"
            loading={siblingSpoolsQuery.isLoading}
            dataSource={siblingSpools}
            pagination={false}
            columns={[
              {
                title: t("spool.fields.id"),
                dataIndex: "id",
                render: (id: number) => <a href={`/spool/show/${id}`}>#{id}</a>,
              },
              {
                title: t("spool.fields.remaining_weight"),
                dataIndex: "remaining_weight",
                align: "right",
                render: (value?: number) => (
                  <NumberFieldUnit
                    value={value ?? ""}
                    unit="g"
                    autoScale={unitScaling}
                    options={{ maximumFractionDigits: 1, minimumFractionDigits: 1 }}
                  />
                ),
              },
              { title: t("spool.fields.location"), dataIndex: "location" },
            ]}
          />
        </>
      )}
      {weightSeries.length >= 2 && (
        <>
          <Title level={4}>{t("spool.weight_history.title")}</Title>
          <WeightHistoryChart series={weightSeries} />
        </>
      )}
      <Title level={4}>{t("spool.usage_history.title")}</Title>
      <Table
        size="small"
        rowKey="id"
        loading={usageEvents.isLoading}
        dataSource={usageEvents.data ?? []}
        pagination={false}
        locale={{ emptyText: t("spool.usage_history.empty") }}
        columns={[
          {
            title: t("spool.usage_history.time"),
            dataIndex: "time",
            render: (value: string) => dayjs.utc(value).local().format(DATE_TIME_FORMAT_SHORT),
          },
          { title: t("spool.usage_history.type"), dataIndex: "event_type" },
          {
            title: t("spool.usage_history.change"),
            dataIndex: "delta",
            align: "right",
            render: (value: number) => `${value > 0 ? "+" : ""}${value.toFixed(1)} g`,
          },
          { title: t("spool.usage_history.comment"), dataIndex: "comment" },
        ]}
      />
    </Show>
  );
};

export default SpoolShow;
