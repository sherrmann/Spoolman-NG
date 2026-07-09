import { useTranslate } from "@refinedev/core";
import { Checkbox, Form, Input, InputNumber, Modal } from "antd";
import { useForm } from "antd/es/form/Form";
import type { MessageInstance } from "antd/es/message/interface";
import { type CSSProperties, useCallback, useMemo, useState } from "react";
import { bulkPatch } from "../../utils/bulkPatch";
import { formatNumberOnUserInput, numberParser } from "../../utils/parsing";
import { getCurrencySymbol, useCurrency } from "../../utils/settings";

const ROW_STYLE: CSSProperties = { display: "flex", alignItems: "center", gap: 8 };
const LABEL_STYLE: CSSProperties = { width: 140, flexShrink: 0 };

/** PATCH `body` onto every selected filament, tolerating partial failure. Returns the count that failed. */
export function bulkPatchFilaments(ids: number[], body: Record<string, unknown>): Promise<number> {
  return bulkPatch("filament", ids, body);
}

// Bulk-editable filament fields (issue #73 / upstream #749). Each is opt-in via a checkbox so an
// unchecked field is never touched across the selection.
type BulkField = "price" | "density" | "settings_extruder_temp" | "settings_bed_temp" | "comment";

/**
 * Bulk-edit modal for the filament list. Applies one set of field changes to many selected filaments
 * by looping the existing single-filament PATCH endpoint (no bulk backend endpoint, so the API surface
 * integrations depend on is unchanged). Only ticked fields are sent.
 */
export function useFilamentBulkEditModal(messageApi: MessageInstance, onApplied: () => void) {
  const t = useTranslate();
  const [form] = useForm();
  const currency = useCurrency();
  const [ids, setIds] = useState<number[] | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const openBulkEdit = useCallback(
    (selectedIds: number[]) => {
      form.resetFields();
      setIds(selectedIds);
    },
    [form],
  );

  const bulkEditModal = useMemo(() => {
    if (ids === null) {
      return null;
    }

    const onFinish = async () => {
      const values = form.getFieldsValue();
      const body: Record<string, unknown> = {};
      if (values.enable_price) body.price = values.price ?? null;
      if (values.enable_density) body.density = values.density ?? null;
      if (values.enable_settings_extruder_temp) body.settings_extruder_temp = values.settings_extruder_temp ?? null;
      if (values.enable_settings_bed_temp) body.settings_bed_temp = values.settings_bed_temp ?? null;
      if (values.enable_comment) body.comment = values.comment ?? "";

      if (Object.keys(body).length === 0) {
        messageApi.info(t("filament.bulk.nothing_selected"));
        return;
      }

      setSubmitting(true);
      const failed = await bulkPatchFilaments(ids, body);
      setSubmitting(false);
      if (failed === 0) {
        messageApi.success(t("filament.bulk.applied", { count: ids.length }));
      } else {
        messageApi.error(t("filament.bulk.applied_partial", { failed, count: ids.length }));
      }
      setIds(null);
      onApplied();
    };

    const enabled = (field: BulkField) => form.getFieldValue(`enable_${field}`) === true;

    return (
      <Modal
        title={t("filament.bulk.edit_title", { count: ids.length })}
        open
        confirmLoading={submitting}
        okText={t("filament.bulk.apply")}
        onCancel={() => setIds(null)}
        onOk={form.submit}
      >
        <p>{t("filament.bulk.edit_help")}</p>
        <Form form={form} onFinish={onFinish}>
          {/* shouldUpdate re-renders the rows when a checkbox flips so the inputs enable/disable live. */}
          <Form.Item noStyle shouldUpdate>
            {() => (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <div style={ROW_STYLE}>
                  <Form.Item name="enable_price" valuePropName="checked" noStyle>
                    <Checkbox />
                  </Form.Item>
                  <span style={LABEL_STYLE}>{t("filament.fields.price")}</span>
                  <Form.Item name="price" noStyle>
                    <InputNumber
                      disabled={!enabled("price")}
                      style={{ flex: 1 }}
                      precision={2}
                      min={0}
                      addonAfter={getCurrencySymbol(undefined, currency)}
                      formatter={formatNumberOnUserInput}
                      parser={numberParser}
                    />
                  </Form.Item>
                </div>
                <div style={ROW_STYLE}>
                  <Form.Item name="enable_density" valuePropName="checked" noStyle>
                    <Checkbox />
                  </Form.Item>
                  <span style={LABEL_STYLE}>{t("filament.fields.density")}</span>
                  <Form.Item name="density" noStyle>
                    <InputNumber
                      disabled={!enabled("density")}
                      style={{ flex: 1 }}
                      precision={2}
                      min={0}
                      addonAfter="g/cm³"
                      formatter={formatNumberOnUserInput}
                      parser={numberParser}
                    />
                  </Form.Item>
                </div>
                <div style={ROW_STYLE}>
                  <Form.Item name="enable_settings_extruder_temp" valuePropName="checked" noStyle>
                    <Checkbox />
                  </Form.Item>
                  <span style={LABEL_STYLE}>{t("filament.fields.settings_extruder_temp")}</span>
                  <Form.Item name="settings_extruder_temp" noStyle>
                    <InputNumber
                      disabled={!enabled("settings_extruder_temp")}
                      style={{ flex: 1 }}
                      min={0}
                      addonAfter="°C"
                    />
                  </Form.Item>
                </div>
                <div style={ROW_STYLE}>
                  <Form.Item name="enable_settings_bed_temp" valuePropName="checked" noStyle>
                    <Checkbox />
                  </Form.Item>
                  <span style={LABEL_STYLE}>{t("filament.fields.settings_bed_temp")}</span>
                  <Form.Item name="settings_bed_temp" noStyle>
                    <InputNumber disabled={!enabled("settings_bed_temp")} style={{ flex: 1 }} min={0} addonAfter="°C" />
                  </Form.Item>
                </div>
                <div style={{ ...ROW_STYLE, alignItems: "flex-start" }}>
                  <Form.Item name="enable_comment" valuePropName="checked" noStyle>
                    <Checkbox />
                  </Form.Item>
                  <span style={LABEL_STYLE}>{t("filament.fields.comment")}</span>
                  <Form.Item name="comment" noStyle style={{ flex: 1, marginBottom: 0 }}>
                    <Input.TextArea disabled={!enabled("comment")} maxLength={1024} rows={2} />
                  </Form.Item>
                </div>
              </div>
            )}
          </Form.Item>
        </Form>
      </Modal>
    );
  }, [ids, submitting, currency, t]);

  return { openBulkEdit, bulkEditModal };
}
