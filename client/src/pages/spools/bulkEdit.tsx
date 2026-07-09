import { useTranslate } from "@refinedev/core";
import { AutoComplete, Checkbox, Form, Input, InputNumber, Modal } from "antd";
import { useForm } from "antd/es/form/Form";
import type { MessageInstance } from "antd/es/message/interface";
import { type CSSProperties, useCallback, useMemo, useState } from "react";
import { formatNumberOnUserInput, numberParser } from "../../utils/parsing";
import { getCurrencySymbol, useCurrency } from "../../utils/settings";
import { getAPIURL } from "../../utils/url";

const ROW_STYLE: CSSProperties = { display: "flex", alignItems: "center", gap: 8 };
const LABEL_STYLE: CSSProperties = { width: 96, flexShrink: 0 };

// Apply a partial change to one spool. Bulk edit loops this over each selected id rather than adding
// a bulk backend endpoint, so the /api/v1 surface (and Moonraker/OctoPrint/HA compatibility) is
// unchanged — see issue #73.
async function patchSpool(id: number, body: Record<string, unknown>): Promise<void> {
  const res = await fetch(`${getAPIURL()}/spool/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`Spool ${id}: HTTP ${res.status}`);
  }
}

/** PATCH `body` onto every id, tolerating partial failure. Returns the count that failed. */
export async function bulkPatchSpools(ids: number[], body: Record<string, unknown>): Promise<number> {
  const results = await Promise.allSettled(ids.map((id) => patchSpool(id, body)));
  return results.filter((r) => r.status === "rejected").length;
}

// The bulk-editable spool fields. Each is opt-in via a checkbox so an unchecked field is never
// touched; a checked-but-empty text field clears the value, matching the single-spool edit form.
type BulkField = "location" | "lot_nr" | "comment" | "price";

/**
 * Bulk-edit modal for the spool list (#73). Applies one set of field changes to many selected spools.
 * Only fields whose "change" checkbox is ticked are sent, so leaving a field alone never overwrites
 * it across the selection.
 */
export function useSpoolBulkEditModal(locationOptions: string[], messageApi: MessageInstance, onApplied: () => void) {
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
      if (values.enable_location) body.location = values.location ?? "";
      if (values.enable_lot_nr) body.lot_nr = values.lot_nr ?? "";
      if (values.enable_comment) body.comment = values.comment ?? "";
      if (values.enable_price) body.price = values.price ?? null;

      if (Object.keys(body).length === 0) {
        messageApi.info(t("spool.bulk.nothing_selected"));
        return;
      }

      setSubmitting(true);
      const failed = await bulkPatchSpools(ids, body);
      setSubmitting(false);
      if (failed === 0) {
        messageApi.success(t("spool.bulk.applied", { count: ids.length }));
      } else {
        messageApi.error(t("spool.bulk.applied_partial", { failed, count: ids.length }));
      }
      setIds(null);
      onApplied();
    };

    // A field's input is enabled only when its "change" checkbox is ticked.
    const enabled = (field: BulkField) => form.getFieldValue(`enable_${field}`) === true;

    return (
      <Modal
        title={t("spool.bulk.edit_title", { count: ids.length })}
        open
        confirmLoading={submitting}
        okText={t("spool.bulk.apply")}
        onCancel={() => setIds(null)}
        onOk={form.submit}
      >
        <p>{t("spool.bulk.edit_help")}</p>
        <Form form={form} onFinish={onFinish}>
          {/* shouldUpdate re-renders the rows when a checkbox flips so the inputs enable/disable live.
              Each row is checkbox + label + the gated input; only ticked fields are applied. */}
          <Form.Item noStyle shouldUpdate>
            {() => (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <div style={ROW_STYLE}>
                  <Form.Item name="enable_location" valuePropName="checked" noStyle>
                    <Checkbox />
                  </Form.Item>
                  <span style={LABEL_STYLE}>{t("spool.fields.location")}</span>
                  <Form.Item name="location" noStyle>
                    {/* AutoComplete (not Select) so a bulk relocate can target a brand-new location,
                        not only ones already in use. */}
                    <AutoComplete
                      allowClear
                      disabled={!enabled("location")}
                      style={{ flex: 1 }}
                      options={locationOptions.map((loc) => ({ value: loc }))}
                      filterOption={(input, option) =>
                        (option?.value ?? "").toLowerCase().includes(input.toLowerCase())
                      }
                      placeholder={t("spool.fields.location")}
                    />
                  </Form.Item>
                </div>
                <div style={ROW_STYLE}>
                  <Form.Item name="enable_lot_nr" valuePropName="checked" noStyle>
                    <Checkbox />
                  </Form.Item>
                  <span style={LABEL_STYLE}>{t("spool.fields.lot_nr")}</span>
                  <Form.Item name="lot_nr" noStyle>
                    <Input disabled={!enabled("lot_nr")} style={{ flex: 1 }} maxLength={64} />
                  </Form.Item>
                </div>
                <div style={ROW_STYLE}>
                  <Form.Item name="enable_price" valuePropName="checked" noStyle>
                    <Checkbox />
                  </Form.Item>
                  <span style={LABEL_STYLE}>{t("spool.fields.price")}</span>
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
                <div style={{ ...ROW_STYLE, alignItems: "flex-start" }}>
                  <Form.Item name="enable_comment" valuePropName="checked" noStyle>
                    <Checkbox />
                  </Form.Item>
                  <span style={LABEL_STYLE}>{t("spool.fields.comment")}</span>
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
  }, [ids, submitting, locationOptions, currency, t]);

  return { openBulkEdit, bulkEditModal };
}
