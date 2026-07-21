import { useCreate, useInvalidate, useTranslate } from "@refinedev/core";
import { AutoComplete, DatePicker, Form, InputNumber, message, Modal, Table } from "antd";
import { useForm } from "antd/es/form/Form";
import dayjs, { Dayjs } from "dayjs";
import utc from "dayjs/plugin/utc";
import { useEffect, useRef, useState } from "react";
import { DATE_FORMAT } from "../../utils/dateFormat";
import { getFilamentName, LowStockRow } from "../home/analytics";
import { buildBulkOrderBody, OrderLineInput } from "./orderBody";
import { useShops } from "./useShops";

dayjs.extend(utc);

interface BulkFormValues {
  shop_name?: string;
  ordered_at: Dayjs;
}

interface Props {
  open: boolean;
  rows: LowStockRow[];
  onClose: () => void;
  onSuccess: () => void;
}

/**
 * US2 bulk create-order modal (#298): opened from the Low Stock page's multi-select. Builds one
 * order with one line per selected filament (`buildBulkOrderBody`) — quantities default to 1 and
 * are editable per row before save. Shop AutoComplete and order-date DatePicker mirror the US1
 * single-line dialog (markOrderedDialog.tsx).
 */
export function CreateOrderModal({ open, rows, onClose, onSuccess }: Props) {
  const t = useTranslate();
  const [form] = useForm<BulkFormValues>();
  const { shops, ensureShop } = useShops();
  const { mutate: createOrder, mutation } = useCreate();
  const invalidate = useInvalidate();
  const [submitting, setSubmitting] = useState(false);
  const [quantities, setQuantities] = useState<Record<number, number>>({});
  // Guards initialization to the open:false→true transition only. `rows` is a dependency
  // (its identity legitimately changes when the caller's selection changes), but a background
  // refetch elsewhere (e.g. the filament list re-fetching while this modal is open) also
  // produces a new `rows` array with the same content — without this guard that re-triggers
  // form.resetFields()/setQuantities() and silently wipes whatever the user has already typed.
  const wasOpenRef = useRef(false);

  useEffect(() => {
    if (open && !wasOpenRef.current) {
      form.resetFields();
      form.setFieldsValue({ ordered_at: dayjs() });
      setQuantities(Object.fromEntries(rows.map((r) => [r.filament.id, 1])));
    }
    wasOpenRef.current = open;
  }, [open, rows, form]);

  const shopOptions = shops.map((s) => ({ value: s.name }));

  const onFinish = async (values: BulkFormValues) => {
    setSubmitting(true);
    try {
      const name = values.shop_name?.trim();
      const shopId = name ? await ensureShop(name) : undefined;
      const lines: OrderLineInput[] = rows.map((r) => ({
        filament_id: r.filament.id,
        quantity: quantities[r.filament.id] ?? 1,
      }));
      const body = buildBulkOrderBody(lines, values.ordered_at.utc().format(), shopId);
      createOrder(
        { resource: "order", values: body, successNotification: false },
        {
          onSuccess: () => {
            invalidate({ resource: "filament", invalidates: ["list"] });
            invalidate({ resource: "order", invalidates: ["list"] });
            setSubmitting(false);
            onSuccess();
            onClose();
          },
          onError: () => {
            setSubmitting(false);
            message.error(t("orders.create_error"));
          },
        },
      );
    } catch {
      setSubmitting(false);
      message.error(t("orders.create_error"));
    }
  };

  return (
    <Modal
      title={t("orders.create_order_title", { count: rows.length })}
      open={open}
      onCancel={onClose}
      onOk={form.submit}
      okText={t("orders.create_order")}
      confirmLoading={submitting || mutation.isPending}
      destroyOnClose
      width={560}
    >
      <Form form={form} layout="vertical" onFinish={onFinish} initialValues={{ ordered_at: dayjs() }}>
        <Form.Item name="shop_name" label={t("orders.shop")}>
          <AutoComplete
            options={shopOptions}
            filterOption={(input, option) => (option?.value ?? "").toLowerCase().includes(input.toLowerCase())}
            placeholder={t("orders.shop_placeholder")}
          />
        </Form.Item>
        <Form.Item name="ordered_at" label={t("orders.order_date")} rules={[{ required: true }]}>
          <DatePicker style={{ width: "100%" }} format={DATE_FORMAT} allowClear={false} />
        </Form.Item>
      </Form>
      <Table<LowStockRow>
        rowKey={(r) => r.filament.id}
        dataSource={rows}
        pagination={false}
        size="small"
        columns={[
          { title: t("spool.fields.filament"), key: "name", render: (_, r) => getFilamentName(r.filament) },
          {
            title: t("orders.quantity"),
            key: "quantity",
            width: 120,
            render: (_, r) => (
              <InputNumber
                min={1}
                value={quantities[r.filament.id] ?? 1}
                onChange={(v) => setQuantities((prev) => ({ ...prev, [r.filament.id]: v ?? 1 }))}
              />
            ),
          },
        ]}
      />
    </Modal>
  );
}

export default CreateOrderModal;
