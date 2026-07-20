import { useCreate, useInvalidate, useTranslate } from "@refinedev/core";
import { AutoComplete, Col, DatePicker, Form, Input, InputNumber, message, Modal, Row } from "antd";
import { useForm } from "antd/es/form/Form";
import dayjs, { Dayjs } from "dayjs";
import utc from "dayjs/plugin/utc";
import { useEffect, useState } from "react";
import { DATE_FORMAT } from "../../utils/dateFormat";
import { getFilamentName } from "../home/analytics";
import { IFilament } from "../filaments/model";
import { buildMarkOrderedBody } from "./orderBody";
import { useShops } from "./useShops";

dayjs.extend(utc);

interface MarkOrderedFormValues {
  shop_name?: string;
  ordered_at: Dayjs;
  quantity: number;
  price_per_unit?: number;
  order_number?: string;
  url?: string;
}

interface Props {
  open: boolean;
  filament?: IFilament;
  onClose: () => void;
  onSuccess: () => void;
}

/**
 * US1 "Mark as ordered" dialog (#298): a one-line order for a single low-stock filament, opened
 * from a per-row action on the dashboard tab (home/index.tsx) and the Low Stock full page
 * (lowstock/index.tsx). Matches ui-review/orders-mock-B-dialog.png — shop AutoComplete (creating a
 * shop inline on submit), an order-date DatePicker defaulted to today but backdatable, quantity,
 * and optional price/order-number/link.
 */
export function MarkOrderedDialog({ open, filament, onClose, onSuccess }: Props) {
  const t = useTranslate();
  const [form] = useForm<MarkOrderedFormValues>();
  const { shops, ensureShop } = useShops();
  const { mutate: createOrder, mutation } = useCreate();
  const invalidate = useInvalidate();
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      form.resetFields();
      form.setFieldsValue({ ordered_at: dayjs(), quantity: 1 });
    }
  }, [open, form]);

  if (!filament) return null;

  const shopOptions = shops.map((s) => ({ value: s.name }));

  const onFinish = async (values: MarkOrderedFormValues) => {
    setSubmitting(true);
    try {
      const name = values.shop_name?.trim();
      const shopId = name ? await ensureShop(name) : undefined;
      const body = buildMarkOrderedBody({
        filament_id: filament.id,
        quantity: values.quantity,
        orderedAt: values.ordered_at.utc().format(),
        shopId,
        pricePerUnit: values.price_per_unit,
        orderNumber: values.order_number,
        url: values.url,
      });
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
      title={t("lowstock.mark_ordered_title", { name: getFilamentName(filament) })}
      open={open}
      onCancel={onClose}
      onOk={form.submit}
      okText={t("orders.mark_ordered")}
      confirmLoading={submitting || mutation.isPending}
      destroyOnClose
    >
      <Form form={form} layout="vertical" onFinish={onFinish} initialValues={{ ordered_at: dayjs(), quantity: 1 }}>
        <Form.Item name="shop_name" label={t("orders.shop")}>
          <AutoComplete
            options={shopOptions}
            filterOption={(input, option) => (option?.value ?? "").toLowerCase().includes(input.toLowerCase())}
            placeholder={t("orders.shop_placeholder")}
          />
        </Form.Item>
        <Row gutter={16}>
          <Col xs={24} md={12}>
            <Form.Item name="ordered_at" label={t("orders.order_date")} rules={[{ required: true }]}>
              <DatePicker style={{ width: "100%" }} format={DATE_FORMAT} allowClear={false} />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item name="quantity" label={t("orders.quantity")} rules={[{ required: true }]}>
              <InputNumber min={1} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={16}>
          <Col xs={24} md={12}>
            <Form.Item name="price_per_unit" label={t("orders.price_per_unit")}>
              <InputNumber min={0} style={{ width: "100%" }} placeholder="21.90" />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item name="order_number" label={t("orders.order_number_field")}>
              <Input maxLength={256} placeholder="e.g. 3DJ-84302" />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item name="url" label={t("orders.url")}>
          <Input placeholder="https://..." maxLength={1024} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

export default MarkOrderedDialog;
