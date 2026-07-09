import { useInvalidate, useTranslate } from "@refinedev/core";
import { Button, Form, InputNumber, Modal, Radio, Select, Typography } from "antd";
import { useForm } from "antd/es/form/Form";
import type { MessageInstance } from "antd/es/message/interface";
import type { InputNumberRef } from "rc-input-number";
import { useCallback, useMemo, useRef, useState } from "react";
import { formatNumberOnUserInput, formatWeight, numberParser } from "../../utils/parsing";
import { useSavedState } from "../../utils/saveload";
import { getAPIURL } from "../../utils/url";
import { useSpoolFilament, useSpoolFilamentMeasure } from "./functions";
import { ISpool } from "./model";

type MeasurementType = "length" | "weight" | "measured_weight";

interface SpoolOption {
  value: number;
  label: string;
  spool: ISpool;
}

function spoolLabel(s: ISpool): string {
  const fil = s.filament;
  const name = fil.vendor?.name ? `${fil.vendor.name} - ${fil.name ?? fil.id}` : (fil.name ?? `Filament ${fil.id}`);
  const remaining = s.remaining_weight != null ? ` · ${formatWeight(s.remaining_weight)}` : "";
  return `#${s.id} · ${name}${remaining}`;
}

/**
 * A header-level "weigh spools" workflow (#99): search for a spool, enter its length/weight/measured
 * weight, and Save & Next to weigh the next one without leaving the dialog — for quickly re-weighing a
 * batch after a multi-colour print. Each save uses the existing single-spool PUT /use or /measure
 * endpoint (the same ones the per-row Adjust dialog and Moonraker use), so no new API is introduced.
 */
export function useBulkWeightUpdateModal(messageApi: MessageInstance) {
  const t = useTranslate();
  const invalidate = useInvalidate();
  const [form] = useForm();
  const [open, setOpen] = useState(false);
  // Share the persisted measurement mode with the per-row Adjust dialog so the user's choice is
  // consistent across both (#117).
  const [measurementType, setMeasurementType] = useSavedState<MeasurementType>("spoolAdjust-measurementType", "length");
  const [options, setOptions] = useState<SpoolOption[]>([]);
  const [selected, setSelected] = useState<ISpool | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const searchTimer = useRef<number | undefined>(undefined);
  const valueRef = useRef<InputNumberRef | null>(null);

  // Server-side spool search (reuses the list `search` param, #51) so this scales to large
  // inventories instead of loading every spool into the dropdown.
  const fetchSpools = useCallback(async (term: string) => {
    const params = new URLSearchParams({ allow_archived: "false", limit: "20" });
    if (term) params.set("search", term);
    const res = await fetch(`${getAPIURL()}/spool?${params.toString()}`);
    if (!res.ok) return;
    const spools: ISpool[] = await res.json();
    setOptions(spools.map((s) => ({ value: s.id, label: spoolLabel(s), spool: s })));
  }, []);

  const onSearch = (term: string) => {
    window.clearTimeout(searchTimer.current);
    searchTimer.current = window.setTimeout(() => void fetchSpools(term), 250);
  };

  const openBulkWeightUpdate = useCallback(() => {
    setSelected(null);
    form.resetFields();
    setOpen(true);
    void fetchSpools("");
  }, [fetchSpools, form]);

  const applyAndNext = useCallback(async () => {
    if (!selected) {
      messageApi.info(t("spool.weigh.pick_spool"));
      return;
    }
    const value = form.getFieldValue("value");
    if (value === undefined || value === null) {
      return;
    }
    setSubmitting(true);
    try {
      if (measurementType === "length") {
        await useSpoolFilament(selected, value, undefined);
      } else if (measurementType === "weight") {
        await useSpoolFilament(selected, undefined, value);
      } else {
        await useSpoolFilamentMeasure(selected, value);
      }
      messageApi.success(t("spool.weigh.updated", { name: spoolLabel(selected) }));
      invalidate({ resource: "spool", invalidates: ["list"] });
      // Save & next: clear the spool and value, keep the dialog open, and refocus for the next one.
      setSelected(null);
      form.setFieldsValue({ spool: undefined, value: undefined });
      void fetchSpools("");
      setTimeout(() => valueRef.current?.focus(), 0);
    } finally {
      setSubmitting(false);
    }
  }, [selected, measurementType, form, messageApi, invalidate, fetchSpools, t]);

  const bulkWeightUpdateModal = useMemo(() => {
    if (!open) {
      return null;
    }
    return (
      <Modal
        title={t("spool.weigh.title")}
        open
        onCancel={() => setOpen(false)}
        footer={[
          <Button key="done" onClick={() => setOpen(false)}>
            {t("spool.weigh.done")}
          </Button>,
          <Button key="save" type="primary" loading={submitting} onClick={applyAndNext}>
            {t("spool.weigh.save_next")}
          </Button>,
        ]}
      >
        <p>{t("spool.weigh.help")}</p>
        <Form form={form} layout="vertical">
          <Form.Item label={t("spool.weigh.spool")} name="spool">
            <Select<number, SpoolOption>
              showSearch
              filterOption={false}
              onSearch={onSearch}
              onChange={(_, opt) => {
                const chosen = Array.isArray(opt) ? opt[0] : opt;
                setSelected(chosen?.spool ?? null);
                setTimeout(() => valueRef.current?.focus(), 0);
              }}
              options={options}
              placeholder={t("spool.weigh.search_placeholder")}
              notFoundContent={null}
            />
          </Form.Item>
          {selected && selected.remaining_weight != null && (
            <Typography.Paragraph type="secondary">
              {t("spool.fields.remaining_weight")}: {formatWeight(selected.remaining_weight)}
            </Typography.Paragraph>
          )}
          <Form.Item label={t("spool.form.measurement_type_label")}>
            <Radio.Group
              value={measurementType}
              onChange={({ target: { value } }) => setMeasurementType(value as MeasurementType)}
            >
              <Radio.Button value="length">{t("spool.form.measurement_type.length")}</Radio.Button>
              <Radio.Button value="weight">{t("spool.form.measurement_type.weight")}</Radio.Button>
              <Radio.Button value="measured_weight">{t("spool.fields.measured_weight")}</Radio.Button>
            </Radio.Group>
          </Form.Item>
          <Form.Item label={t("spool.form.adjust_filament_value")} name="value">
            <InputNumber
              ref={valueRef}
              precision={1}
              addonAfter={measurementType === "length" ? "mm" : "g"}
              formatter={formatNumberOnUserInput}
              parser={numberParser}
              onPressEnter={applyAndNext}
            />
          </Form.Item>
        </Form>
      </Modal>
    );
  }, [open, options, selected, measurementType, submitting, applyAndNext, form, t]);

  return { openBulkWeightUpdate, bulkWeightUpdateModal };
}
