import { UploadOutlined } from "@ant-design/icons";
import { useList, useTranslate } from "@refinedev/core";
import { Button, Select, Space, Table, Typography, Upload, message } from "antd";
import type { UploadFile } from "antd";
import { useState } from "react";
import SpoolIcon from "../../components/spoolIcon";
import { applySpoolUsage } from "../../utils/importExport";
import { formatWeight } from "../../utils/parsing";
import { ThreeMfFilament, autoMatchSpoolId, parseThreeMf } from "../../utils/threeMfImport";
import { getSpoolName } from "../home/analytics";
import { ISpool } from "../spools/model";

const { Paragraph } = Typography;

/**
 * Import a sliced .3mf project (#105): read each plate's per-filament colour/type/usage, auto-match
 * to an in-stock spool (overridable), then record the consumed grams on the chosen spools via the
 * existing PUT /use — reusing the same per-row apply the bulk workflows (#73/#99) rely on rather than
 * adding a backend endpoint. Lives inside the opt-in Import/Export settings page, so nothing new is
 * added to the main navigation.
 */
export function ThreeMfImportSection() {
  const t = useTranslate();
  const [messageApi, contextHolder] = message.useMessage();
  const spoolsQuery = useList<ISpool>({
    resource: "spool",
    pagination: { mode: "off" },
    meta: { queryParams: { allow_archived: false } },
  });
  const spools = spoolsQuery.result?.data ?? [];

  const [rows, setRows] = useState<ThreeMfFilament[]>([]);
  const [selected, setSelected] = useState<Record<string, number | undefined>>({});
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [applying, setApplying] = useState(false);

  const reset = () => {
    setRows([]);
    setSelected({});
    setFileList([]);
  };

  const loadFile = (file: UploadFile & { arrayBuffer: () => Promise<ArrayBuffer> }) => {
    file.arrayBuffer().then((buf) => {
      try {
        const parsed = parseThreeMf(new Uint8Array(buf));
        if (parsed.length === 0) {
          messageApi.warning(t("settings.import_export.threemf.no_filaments"));
        }
        setRows(parsed);
        const initial: Record<string, number | undefined> = {};
        for (const f of parsed) {
          initial[f.key] = autoMatchSpoolId(f, spools);
        }
        setSelected(initial);
        setFileList([{ uid: file.uid, name: file.name, status: "done" }]);
      } catch (e) {
        messageApi.error(e instanceof Error ? e.message : String(e));
        reset();
      }
    });
  };

  const spoolOptions = spools.map((s) => ({
    value: s.id,
    label: `#${s.id} · ${getSpoolName(s)}${s.location ? ` · ${s.location}` : ""}`,
  }));

  const anySelected = rows.some((r) => selected[r.key] !== undefined);

  const apply = async () => {
    setApplying(true);
    let ok = 0;
    let fail = 0;
    for (const row of rows) {
      const spoolId = selected[row.key];
      if (spoolId === undefined || row.usedWeight <= 0) {
        continue;
      }
      try {
        await applySpoolUsage(spoolId, row.usedWeight);
        ok += 1;
      } catch {
        fail += 1;
      }
    }
    setApplying(false);
    if (fail > 0) {
      messageApi.warning(t("settings.import_export.threemf.applied_partial", { ok, fail }));
    } else if (ok > 0) {
      messageApi.success(t("settings.import_export.threemf.applied", { count: ok }));
    }
    reset();
    spoolsQuery.query.refetch();
  };

  return (
    <>
      <Paragraph type="secondary">{t("settings.import_export.threemf.help")}</Paragraph>
      <Upload
        accept=".3mf"
        maxCount={1}
        fileList={fileList}
        beforeUpload={(file) => {
          loadFile(file);
          // Prevent antd from uploading; we read the file client-side.
          return false;
        }}
        onRemove={reset}
      >
        <Button icon={<UploadOutlined />}>{t("settings.import_export.threemf.choose_file")}</Button>
      </Upload>
      {rows.length > 0 && (
        <>
          <Table<ThreeMfFilament>
            style={{ marginTop: 12 }}
            size="small"
            rowKey="key"
            pagination={false}
            dataSource={rows}
            columns={[
              {
                title: t("settings.import_export.threemf.col_filament"),
                render: (_, r) => (
                  <Space>
                    {r.colorHex && <SpoolIcon color={r.colorHex} no_margin />}
                    <span>{r.type ?? "?"}</span>
                  </Space>
                ),
              },
              {
                title: t("settings.import_export.threemf.col_used"),
                align: "right",
                render: (_, r) => formatWeight(r.usedWeight, 1),
              },
              {
                title: t("settings.import_export.threemf.col_spool"),
                render: (_, r) => (
                  <Select
                    allowClear
                    showSearch
                    optionFilterProp="label"
                    style={{ minWidth: 240 }}
                    placeholder={t("settings.import_export.threemf.no_match")}
                    value={selected[r.key]}
                    options={spoolOptions}
                    onChange={(v) => setSelected((prev) => ({ ...prev, [r.key]: v }))}
                  />
                ),
              },
            ]}
          />
          <Button type="primary" style={{ marginTop: 12 }} loading={applying} disabled={!anySelected} onClick={apply}>
            {t("settings.import_export.threemf.apply")}
          </Button>
        </>
      )}
      {contextHolder}
    </>
  );
}

export default ThreeMfImportSection;
