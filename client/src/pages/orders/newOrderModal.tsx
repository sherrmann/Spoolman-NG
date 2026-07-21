import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import { useCreate, useInvalidate, useTranslate } from "@refinedev/core";
import { AutoComplete, Button, Col, DatePicker, Form, Input, InputNumber, message, Modal, Row, Select } from "antd";
import { useForm } from "antd/es/form/Form";
import dayjs, { Dayjs } from "dayjs";
import utc from "dayjs/plugin/utc";
import { useEffect, useMemo, useRef, useState } from "react";
import SpoolIcon from "../../components/spoolIcon";
import { DATE_FORMAT } from "../../utils/dateFormat";
import { searchMatches } from "../../utils/filtering";
import { IFilament } from "../filaments/model";
import { FilamentColor, filamentColorObj, formatFilamentLabel } from "../spools/functions";
import { buildNewOrderBody, OrderLineInput } from "./orderBody";
import { useShops } from "./useShops";
import "./orders.css";

dayjs.extend(utc);

interface NewOrderFormValues {
  shop_name?: string;
  ordered_at: Dayjs;
  order_number?: string;
  url?: string;
  comment?: string;
}

// A draft line in the builder. `key` is a stable identity for React/edit tracking; `filament_id`
// is undefined until the user picks one (an incomplete line is dropped on save).
interface DraftLine {
  key: number;
  filament_id?: number;
  quantity: number;
  price_per_unit?: number;
}

interface Props {
  open: boolean;
  filaments: IFilament[];
  onClose: () => void;
  onSuccess: () => void;
}

/**
 * From-scratch "New order" builder (#324): opened by the Orders page's "+ New order" button, which
 * used to be a disabled placeholder — orders were only born from the Low Stock flows. It mirrors the
 * order details/edit modal's header surface (shop AutoComplete, order-date DatePicker, order number,
 * url, comment) but, since there is no existing order to seed lines from, adds a filament picker +
 * lines editor: each line chooses a filament and its quantity/price, with add/remove. On save a
 * POST /order is built by `buildNewOrderBody` (create semantics — blank optional fields omitted).
 */
export function NewOrderModal({ open, filaments, onClose, onSuccess }: Props) {
  const t = useTranslate();
  const [form] = useForm<NewOrderFormValues>();
  const { shops, ensureShop } = useShops();
  const { mutate: createOrder, mutation } = useCreate();
  const invalidate = useInvalidate();
  const [submitting, setSubmitting] = useState(false);
  const [lines, setLines] = useState<DraftLine[]>([]);
  // Monotonic key source for new draft lines (see DraftLine.key). A ref, not state, so bumping it
  // never triggers a render on its own.
  const nextKey = useRef(0);
  // Guards initialization to the open:false→true transition only (same convention as
  // createOrderModal.tsx / orderDetailsModal.tsx) — a background refetch of the filament list while
  // this stays open must not reset the form or wipe lines the user already built.
  const wasOpenRef = useRef(false);

  useEffect(() => {
    if (open && !wasOpenRef.current) {
      form.resetFields();
      form.setFieldsValue({ ordered_at: dayjs() });
      setLines([{ key: 0, quantity: 1 }]);
      nextKey.current = 1;
    }
    wasOpenRef.current = open;
  }, [open, form]);

  const shopOptions = shops.map((s) => ({ value: s.name }));

  // Internal filaments only — an order line references a real filament row. Same label/colour
  // treatment as the spool-create picker (functions.tsx), sorted case-insensitively by label.
  const filamentOptions = useMemo(
    () =>
      filaments
        .map((f) => ({
          label: formatFilamentLabel(f.name ?? `ID ${f.id}`, f.diameter, f.vendor?.name, f.material, f.weight),
          value: f.id,
          colorObj: filamentColorObj(
            f.color_hex,
            f.multi_color_hexes ? f.multi_color_hexes.split(",") : undefined,
            f.multi_color_direction,
          ),
        }))
        .sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: "base" })),
    [filaments],
  );

  const addLine = () => {
    const key = nextKey.current++;
    setLines((prev) => [...prev, { key, quantity: 1 }]);
  };
  const removeLine = (key: number) => setLines((prev) => prev.filter((l) => l.key !== key));
  const updateLine = (key: number, patch: Partial<DraftLine>) =>
    setLines((prev) => prev.map((l) => (l.key === key ? { ...l, ...patch } : l)));

  // An order needs at least one line with a filament actually chosen; the OK button gates on this.
  const hasValidLine = lines.some((l) => l.filament_id != null);

  const onFinish = async (values: NewOrderFormValues) => {
    const orderLines: OrderLineInput[] = lines
      .filter((l): l is DraftLine & { filament_id: number } => l.filament_id != null)
      .map((l) => {
        const line: OrderLineInput = { filament_id: l.filament_id, quantity: l.quantity };
        if (l.price_per_unit !== undefined) line.price_per_unit = l.price_per_unit;
        return line;
      });
    if (orderLines.length === 0) {
      message.error(t("orders.no_lines"));
      return;
    }
    setSubmitting(true);
    try {
      const name = values.shop_name?.trim();
      const shopId = name ? await ensureShop(name) : undefined;
      const body = buildNewOrderBody({
        orderedAt: values.ordered_at.utc().format(),
        lines: orderLines,
        shopId,
        orderNumber: values.order_number?.trim(),
        url: values.url?.trim(),
        comment: values.comment?.trim(),
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
      title={t("orders.new_order_title")}
      open={open}
      onCancel={onClose}
      onOk={form.submit}
      okText={t("orders.create_order")}
      okButtonProps={{ disabled: !hasValidLine }}
      confirmLoading={submitting || mutation.isPending}
      destroyOnClose
      width={640}
    >
      <Form form={form} layout="vertical" onFinish={onFinish} initialValues={{ ordered_at: dayjs() }}>
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
              <Input maxLength={256} placeholder="e.g. 3DJ-84302" />
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
      <div className="order-details-lines">
        <div className="order-details-lines-header">{t("orders.lines_summary_title")}</div>
        {lines.map((line) => (
          <div key={line.key} className="order-details-line">
            <Select
              className="new-order-line-filament"
              showSearch
              value={line.filament_id}
              placeholder={t("orders.select_filament")}
              aria-label={t("spool.fields.filament")}
              options={filamentOptions}
              filterOption={(input, option) => typeof option?.label === "string" && searchMatches(input, option.label)}
              optionRender={(oriOption) => (
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ display: "inline-flex", flex: "0 0 auto", fontSize: "0.6em" }}>
                    <SpoolIcon color={(oriOption.data as { colorObj?: FilamentColor }).colorObj} no_margin />
                  </span>
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{oriOption.label}</span>
                </div>
              )}
              onChange={(v) => updateLine(line.key, { filament_id: v ?? undefined })}
            />
            <InputNumber
              min={1}
              value={line.quantity}
              aria-label={t("orders.quantity")}
              onChange={(v) => updateLine(line.key, { quantity: v ?? 1 })}
            />
            <InputNumber
              min={0}
              value={line.price_per_unit}
              placeholder="21.90"
              aria-label={t("orders.price_per_unit")}
              onChange={(v) => updateLine(line.key, { price_per_unit: v ?? undefined })}
            />
            <Button
              type="text"
              icon={<DeleteOutlined />}
              aria-label={t("orders.remove_line")}
              onClick={() => removeLine(line.key)}
            />
          </div>
        ))}
        <Button type="dashed" icon={<PlusOutlined />} onClick={addLine} block>
          {t("orders.add_line")}
        </Button>
      </div>
    </Modal>
  );
}

export default NewOrderModal;
