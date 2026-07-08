import { DownloadOutlined, PrinterOutlined, UploadOutlined } from "@ant-design/icons";
import { useList, useTranslate } from "@refinedev/core";
import { Button, Card, Checkbox, Divider, Select, Space, Table, Typography, Upload, message } from "antd";
import type { UploadFile } from "antd";
import dayjs from "dayjs";
import { useRef, useState } from "react";
import { useReactToPrint } from "react-to-print";
import { formatWeight } from "../../utils/parsing";
import { useCurrencyFormatter } from "../../utils/settings";
import {
  DataFormat,
  ExportEntity,
  ImportEntity,
  ImportMode,
  downloadExport,
  importData,
  importSucceeded,
} from "../../utils/importExport";
import { materialBreakdown, totalRemainingWeight, totalValue } from "../home/analytics";
import { ISpool } from "../spools/model";

const { Title, Text, Paragraph } = Typography;

const EXPORT_ENTITIES: ExportEntity[] = ["spools", "filaments", "vendors"];

export function ImportExportSettings() {
  const t = useTranslate();
  const [messageApi, contextHolder] = message.useMessage();
  const currencyFormatter = useCurrencyFormatter();

  // --- Export -------------------------------------------------------------
  const handleDownload = async (entity: ExportEntity, fmt: DataFormat) => {
    try {
      await downloadExport(entity, fmt);
    } catch (e) {
      messageApi.error(e instanceof Error ? e.message : String(e));
    }
  };

  // --- Import -------------------------------------------------------------
  const [importEntity, setImportEntity] = useState<ImportEntity>("spool");
  const [importFormat, setImportFormat] = useState<DataFormat>("json");
  const [importMode, setImportMode] = useState<ImportMode>("create");
  const [dryRun, setDryRun] = useState(true);
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [fileText, setFileText] = useState<string>("");
  const [importing, setImporting] = useState(false);

  const runImport = async () => {
    if (!fileText) {
      messageApi.warning(t("settings.import_export.no_file"));
      return;
    }
    setImporting(true);
    try {
      const result = await importData(importEntity, importFormat, importMode, dryRun, fileText);
      const summary = t("settings.import_export.result", {
        created: result.created,
        updated: result.updated,
        skipped: result.skipped,
      });
      if (!importSucceeded(result)) {
        messageApi.error(`${t("settings.import_export.import_errors")}: ${result.errors.slice(0, 3).join("; ")}`);
      } else if (result.dry_run) {
        messageApi.info(`${t("settings.import_export.dry_run_prefix")} ${summary}`);
      } else {
        messageApi.success(summary);
      }
    } catch (e) {
      messageApi.error(e instanceof Error ? e.message : String(e));
    } finally {
      setImporting(false);
    }
  };

  // --- Printable inventory report (#95) -----------------------------------
  const spoolsQuery = useList<ISpool>({
    resource: "spool",
    pagination: { mode: "off" },
    meta: { queryParams: { allow_archived: false } },
  });
  const spools = spoolsQuery.result?.data ?? [];
  const reportRef = useRef<HTMLDivElement>(null);
  const printReport = useReactToPrint({ contentRef: reportRef });
  const materials = materialBreakdown(spools);

  return (
    <>
      <Title level={4}>{t("settings.import_export.export_title")}</Title>
      <Paragraph type="secondary">{t("settings.import_export.export_help")}</Paragraph>
      <Space direction="vertical" style={{ width: "100%" }}>
        {EXPORT_ENTITIES.map((entity) => (
          <Space key={entity}>
            <Text style={{ display: "inline-block", width: 90 }}>{t(`settings.import_export.entities.${entity}`)}</Text>
            <Button icon={<DownloadOutlined />} onClick={() => handleDownload(entity, "csv")}>
              CSV
            </Button>
            <Button icon={<DownloadOutlined />} onClick={() => handleDownload(entity, "json")}>
              JSON
            </Button>
          </Space>
        ))}
      </Space>

      <Divider />

      <Title level={4}>{t("settings.import_export.import_title")}</Title>
      <Paragraph type="secondary">{t("settings.import_export.import_help")}</Paragraph>
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        <Space wrap>
          <Select<ImportEntity>
            value={importEntity}
            onChange={setImportEntity}
            style={{ width: 140 }}
            options={[
              { value: "vendor", label: t("settings.import_export.entities.vendors") },
              { value: "filament", label: t("settings.import_export.entities.filaments") },
              { value: "spool", label: t("settings.import_export.entities.spools") },
            ]}
          />
          <Select<DataFormat>
            value={importFormat}
            onChange={setImportFormat}
            style={{ width: 100 }}
            options={[
              { value: "json", label: "JSON" },
              { value: "csv", label: "CSV" },
            ]}
          />
          <Select<ImportMode>
            value={importMode}
            onChange={setImportMode}
            style={{ width: 180 }}
            options={[
              { value: "create", label: t("settings.import_export.modes.create") },
              { value: "upsert", label: t("settings.import_export.modes.upsert") },
              { value: "skip_existing", label: t("settings.import_export.modes.skip_existing") },
            ]}
          />
          <Checkbox checked={dryRun} onChange={(e) => setDryRun(e.target.checked)}>
            {t("settings.import_export.dry_run")}
          </Checkbox>
        </Space>
        <Upload
          accept=".csv,.json,text/csv,application/json"
          maxCount={1}
          fileList={fileList}
          beforeUpload={(file) => {
            file.text().then((text) => {
              setFileText(text);
              if (file.name.endsWith(".csv")) setImportFormat("csv");
              else if (file.name.endsWith(".json")) setImportFormat("json");
            });
            setFileList([{ uid: file.uid, name: file.name, status: "done" }]);
            // Prevent antd from uploading; we read the file client-side.
            return false;
          }}
          onRemove={() => {
            setFileList([]);
            setFileText("");
          }}
        >
          <Button icon={<UploadOutlined />}>{t("settings.import_export.choose_file")}</Button>
        </Upload>
        <Button type="primary" loading={importing} disabled={!fileText} onClick={runImport}>
          {dryRun ? t("settings.import_export.validate") : t("settings.import_export.import_button")}
        </Button>
      </Space>

      <Divider />

      <Title level={4}>{t("settings.import_export.report_title")}</Title>
      <Paragraph type="secondary">{t("settings.import_export.report_help")}</Paragraph>
      <Button icon={<PrinterOutlined />} onClick={() => printReport()} loading={spoolsQuery.query.isLoading}>
        {t("settings.import_export.print_report")}
      </Button>

      {/* Off-screen printable report. */}
      <div style={{ position: "absolute", left: "-10000px", top: 0 }} aria-hidden>
        <div ref={reportRef} style={{ padding: 24, color: "#000", background: "#fff" }}>
          <style>{`@media print { html, body { -webkit-print-color-adjust: exact; } }`}</style>
          <Title level={3} style={{ color: "#000" }}>
            {t("settings.import_export.report_heading")}
          </Title>
          <Text style={{ color: "#000" }}>{dayjs().format("YYYY-MM-DD HH:mm")}</Text>
          <Card size="small" style={{ marginTop: 12 }}>
            <Space size="large" wrap>
              <span>
                {t("settings.import_export.entities.spools")}: <strong>{spools.length}</strong>
              </span>
              <span>
                {t("home.total_weight")}: <strong>{formatWeight(totalRemainingWeight(spools), 0)}</strong>
              </span>
              <span>
                {t("home.total_value")}: <strong>{currencyFormatter.format(totalValue(spools))}</strong>
              </span>
            </Space>
          </Card>
          <Table<[string, { count: number; weight: number }]>
            style={{ marginTop: 12 }}
            size="small"
            pagination={false}
            rowKey={(row) => row[0]}
            dataSource={materials}
            columns={[
              { title: t("spool.fields.material"), dataIndex: 0, render: (_, row) => row[0] },
              {
                title: t("filament.fields.spool_count"),
                align: "right",
                render: (_, row) => row[1].count,
              },
              {
                title: t("home.total_weight"),
                align: "right",
                render: (_, row) => formatWeight(row[1].weight, 0),
              },
            ]}
          />
        </div>
      </div>
      {contextHolder}
    </>
  );
}
