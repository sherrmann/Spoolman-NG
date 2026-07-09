import { useTranslate } from "@refinedev/core";
import { Form, Modal, Spin, message } from "antd";
import { useEffect, useState } from "react";
import { ExtraFieldFormItem, ParsedExtras, StringifiedExtras } from "../../../components/extraFields";
import { EntityType, useGetFields } from "../../../utils/queryFields";
import { getOrCreateLocationByName, updateLocationExtra } from "../functions";
import { ILocation } from "../model";

/**
 * Edit the custom-field values of a single location (#103). The board deals in location strings, so
 * on open we lazily get-or-create the Location entity for this name, then edit its extra fields with
 * the same ExtraFieldFormItem the entity create forms use. Only mounted by the board when location
 * custom fields exist, so it never adds clutter to a plain locations board.
 */
export function LocationFieldsModal({
  locationName,
  open,
  onClose,
}: {
  locationName: string;
  open: boolean;
  onClose: () => void;
}) {
  const t = useTranslate();
  const [form] = Form.useForm();
  const fields = useGetFields(EntityType.location);
  const [location, setLocation] = useState<ILocation | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setLocation(null);
    form.resetFields();
    getOrCreateLocationByName(locationName)
      .then((loc) => {
        if (cancelled) return;
        setLocation(loc);
        // Parse the JSON-encoded stored values into real types for the form inputs.
        form.setFieldsValue({ extra: ParsedExtras({ extra: loc.extra }).extra ?? {} });
      })
      .catch(() => {
        if (!cancelled) message.error(t("locations.fields.load_error"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // form/t are stable; intentionally re-run only when the modal opens for a (possibly new) location.
  }, [open, locationName]);

  const onSave = async () => {
    if (!location) return;
    let values: { extra?: { [key: string]: string } };
    try {
      values = StringifiedExtras(await form.validateFields());
    } catch {
      return; // validation errors are rendered inline by the form
    }
    setSaving(true);
    try {
      await updateLocationExtra(location.id, values.extra ?? {});
      message.success(t("locations.fields.saved"));
      onClose();
    } catch {
      message.error(t("locations.fields.save_error"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={t("locations.fields.title", { name: locationName })}
      open={open}
      onCancel={onClose}
      onOk={onSave}
      confirmLoading={saving}
      okButtonProps={{ disabled: loading }}
      destroyOnClose
    >
      {loading ? (
        <div style={{ display: "flex", justifyContent: "center", padding: 24 }}>
          <Spin />
        </div>
      ) : (
        <Form form={form} layout="vertical">
          {fields.data?.map((field, index) => (
            <ExtraFieldFormItem key={index} field={field} />
          ))}
        </Form>
      )}
    </Modal>
  );
}
