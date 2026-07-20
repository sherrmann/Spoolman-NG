import { DeleteOutlined } from "@ant-design/icons";
import { useDelete, useInvalidate, useTranslate, useUpdate } from "@refinedev/core";
import { AutoComplete, Button, Col, DatePicker, Form, Input, InputNumber, message, Modal, Row } from "antd";
import { useForm } from "antd/es/form/Form";
import dayjs, { Dayjs } from "dayjs";
import utc from "dayjs/plugin/utc";
import { useEffect, useRef, useState } from "react";
import { DATE_FORMAT } from "../../utils/dateFormat";
import { safeHttpUrl } from "../../utils/url";
import { getFilamentName } from "../home/analytics";
import { IFilament } from "../filaments/model";
import { buildEditedLines, buildOrderPatchBody, LineEdit } from "./orderEditBody";
import { IOrder } from "./model";
import { useShops } from "./useShops";
import "./orders.css";

dayjs.extend(utc);

interface DetailsFormValues {
  shop_name?: string;
  ordered_at: Dayjs;
  order_number?: string;
  url?: string;
  comment?: string;
}

interface Props {
  open: boolean;
  order?: IOrder;
  filamentsById: Map<number, IFilament>;
  onClose: () => void;
  onSuccess: () => void;
}

/**
 * Order details/edit modal (gate-feedback item #5): opened by clicking an order row (or its
 * order # link) on the Orders list — replaces the old antd Table row-expander. Shows the shop,
 * ordered date, order number, url (as a safe link — see safeHttpUrl's docstring) and comment, all
 * editable via the same shop-AutoComplete/DatePicker pattern as markOrderedDialog.tsx. Each line's
 * quantity and price/spool are editable while still outstanding; already-arrived lines render
 * read-only with their arrived state. Saving PATCHes /order/{id}: since the backend fully replaces
 * the line set whenever `lines` is present (see orderEditBody.ts's docstring), every line is sent
 * back — buildEditedLines folds the per-row edits over the order's original lines so arrived ones
 * go out unchanged. Delete removes the order (and cascades its lines) after a confirm, matching
 * the spools/show.tsx delete pattern.
 */
export function OrderDetailsModal({ open, order, filamentsById, onClose, onSuccess }: Props) {
  const t = useTranslate();
  const [form] = useForm<DetailsFormValues>();
  const { shops, ensureShop } = useShops();
  const { mutate: updateOrder, mutation: updateMutation } = useUpdate();
  const { mutate: deleteOrder, mutation: deleteMutation } = useDelete();
  const invalidate = useInvalidate();
  const [submitting, setSubmitting] = useState(false);
  const [lineEdits, setLineEdits] = useState<Record<number, LineEdit>>({});
  // Guards the open:false→true transition only (same convention as createOrderModal.tsx's
  // wasOpenRef) — a background refetch of the order/filament lists while this stays open must not
  // reset the form or wipe edits the user already made.
  const wasOpenRef = useRef(false);

  useEffect(() => {
    if (open && !wasOpenRef.current && order) {
      form.resetFields();
      form.setFieldsValue({
        shop_name: order.shop?.name,
        ordered_at: dayjs(order.ordered_at),
        order_number: order.order_number,
        url: order.url,
        comment: order.comment,
      });
      setLineEdits(
        Object.fromEntries(
          order.lines
            .filter((l) => !l.arrived_at)
            .map((l) => [l.id, { quantity: l.quantity, price_per_unit: l.price_per_unit }]),
        ),
      );
    }
    wasOpenRef.current = open;
  }, [open, order, form]);

  if (!order) return null;

  const shopOptions = shops.map((s) => ({ value: s.name }));
  const orderLabel = order.order_number ?? `#${order.id}`;
  const href = safeHttpUrl(order.url);

  const invalidateAfterChange = () => {
    invalidate({ resource: "order", invalidates: ["list"] });
    invalidate({ resource: "filament", invalidates: ["list"] });
    invalidate({ resource: "spool", invalidates: ["list"] });
  };

  const onFinish = async (values: DetailsFormValues) => {
    setSubmitting(true);
    try {
      const name = values.shop_name?.trim();
      const shopId = name ? await ensureShop(name) : null;
      const lines = buildEditedLines(order.lines, lineEdits);
      const body = buildOrderPatchBody(
        {
          shopId,
          orderedAt: values.ordered_at.utc().format(),
          orderNumber: values.order_number ?? "",
          url: values.url ?? "",
          comment: values.comment ?? "",
        },
        lines,
      );
      updateOrder(
        { resource: "order", id: order.id, values: body, successNotification: false },
        {
          onSuccess: () => {
            invalidateAfterChange();
            setSubmitting(false);
            onSuccess();
            onClose();
          },
          onError: () => {
            setSubmitting(false);
            message.error(t("orders.update_error"));
          },
        },
      );
    } catch {
      setSubmitting(false);
      message.error(t("orders.update_error"));
    }
  };

  const handleDelete = () => {
    Modal.confirm({
      title: t("buttons.confirm"),
      content: t("orders.delete_confirm"),
      okText: t("buttons.delete"),
      okType: "danger",
      cancelText: t("buttons.cancel"),
      onOk: () =>
        new Promise<void>((resolve, reject) => {
          deleteOrder(
            { resource: "order", id: order.id, successNotification: false },
            {
              onSuccess: () => {
                invalidateAfterChange();
                resolve();
                onSuccess();
                onClose();
              },
              onError: (error) => {
                message.error(t("orders.delete_error"));
                reject(error);
              },
            },
          );
        }),
    });
  };

  return (
    <Modal
      title={t("orders.details_title", { number: orderLabel })}
      open={open}
      onCancel={onClose}
      destroyOnClose
      width={640}
      footer={[
        <Button key="delete" danger icon={<DeleteOutlined />} loading={deleteMutation.isPending} onClick={handleDelete}>
          {t("buttons.delete")}
        </Button>,
        <Button key="cancel" onClick={onClose}>
          {t("buttons.cancel")}
        </Button>,
        <Button
          key="save"
          type="primary"
          loading={submitting || updateMutation.isPending}
          onClick={() => form.submit()}
        >
          {t("buttons.save")}
        </Button>,
      ]}
    >
      <Form form={form} layout="vertical" onFinish={onFinish}>
        <Row gutter={16}>
          <Col xs={24} md={12}>
            <Form.Item name="shop_name" label={t("orders.shop")}>
              <AutoComplete
                options={shopOptions}
                filterOption={(input, option) => (option?.value ?? "").toLowerCase().includes(input.toLowerCase())}
                placeholder={t("orders.shop_placeholder")}
              />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item name="ordered_at" label={t("orders.order_date")} rules={[{ required: true }]}>
              <DatePicker style={{ width: "100%" }} format={DATE_FORMAT} allowClear={false} />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={16}>
          <Col xs={24} md={12}>
            <Form.Item name="order_number" label={t("orders.order_number_field")}>
              <Input maxLength={256} />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item name="url" label={t("orders.url")}>
              <Input placeholder="https://..." maxLength={1024} />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item name="comment" label={t("orders.comment")}>
          <Input.TextArea maxLength={1024} rows={2} />
        </Form.Item>
      </Form>
      {href && (
        <div className="order-details-link">
          <a href={href} target="_blank" rel="noreferrer noopener">
            {href}
          </a>
        </div>
      )}
      <div className="order-details-lines">
        <div className="order-details-lines-header">{t("orders.lines_summary_title")}</div>
        {order.lines.map((line) => {
          const filament = filamentsById.get(line.filament_id);
          const name = filament ? getFilamentName(filament) : `#${line.filament_id}`;

          if (line.arrived_at) {
            return (
              <div key={line.id} className="order-details-line order-details-line-arrived">
                <span className="order-details-line-name">{name}</span>
                <span className="order-details-line-qty">× {line.quantity}</span>
                <span className="order-details-line-price">
                  {line.price_per_unit != null ? line.price_per_unit : "—"}
                </span>
                <span className="order-details-line-state">✓ {t("orders.state.arrived")}</span>
              </div>
            );
          }

          const edit = lineEdits[line.id] ?? { quantity: line.quantity, price_per_unit: line.price_per_unit };
          return (
            <div key={line.id} className="order-details-line">
              <span className="order-details-line-name">{name}</span>
              <InputNumber
                min={1}
                value={edit.quantity}
                aria-label={t("orders.quantity")}
                onChange={(v) => setLineEdits((prev) => ({ ...prev, [line.id]: { ...edit, quantity: v ?? 1 } }))}
              />
              <InputNumber
                min={0}
                value={edit.price_per_unit}
                placeholder="21.90"
                aria-label={t("orders.price_per_unit")}
                onChange={(v) =>
                  setLineEdits((prev) => ({ ...prev, [line.id]: { ...edit, price_per_unit: v ?? undefined } }))
                }
              />
              <span className="order-details-line-state">{t("orders.outstanding")}</span>
            </div>
          );
        })}
      </div>
    </Modal>
  );
}

export default OrderDetailsModal;
