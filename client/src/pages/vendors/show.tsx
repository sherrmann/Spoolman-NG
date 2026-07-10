import { DATE_TIME_FORMAT } from "../../utils/dateFormat";
import { FileOutlined } from "@ant-design/icons";
import { DateField, NumberField, Show, TextField } from "@refinedev/antd";
import { useShow, useTranslate } from "@refinedev/core";
import { Button, Descriptions, Typography } from "antd";
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import { useNavigate } from "react-router";
import { ExtraFieldDisplay } from "../../components/extraFields";
import { enrichText } from "../../utils/parsing";
import { EntityType, useGetFields } from "../../utils/queryFields";
import { IVendor } from "./model";

dayjs.extend(utc);

const { Title } = Typography;

/**
 * Build a link to the Spool list pre-filtered to this vendor, encoding the filter into the
 * URL hash exactly as the list persists it (see utils/saveload.ts). The quoted value is an
 * exact-match term matching how the vendor filter column stores selections. Issue #86.
 */
function viewSpoolsHref(vendorName: string): string {
  const params = new URLSearchParams();
  params.set(
    "filters",
    JSON.stringify([{ field: "filament.vendor.name", operator: "in", value: [`"${vendorName}"`] }]),
  );
  return `/spool#${params.toString()}`;
}

export const VendorShow = () => {
  const t = useTranslate();
  const navigate = useNavigate();
  const extraFields = useGetFields(EntityType.vendor);

  const { query } = useShow<IVendor>({
    liveMode: "auto",
  });
  const { data, isLoading } = query;

  const record = data?.data;

  const formatTitle = (item: IVendor) => {
    return t("vendor.titles.show_title", { id: item.id, name: item.name, interpolation: { escapeValue: false } });
  };

  return (
    <Show
      isLoading={isLoading}
      title={record ? formatTitle(record) : ""}
      headerButtons={({ defaultButtons }) => (
        <>
          {record?.name ? (
            <Button icon={<FileOutlined />} onClick={() => navigate(viewSpoolsHref(record.name as string))}>
              {t("vendor.titles.view_spools")}
            </Button>
          ) : null}
          {defaultButtons}
        </>
      )}
    >
      <Descriptions column={1} bordered size="small">
        <Descriptions.Item label={t("vendor.fields.id")}>
          <NumberField value={record?.id ?? ""} />
        </Descriptions.Item>
        <Descriptions.Item label={t("vendor.fields.registered")}>
          <DateField
            value={dayjs.utc(record?.registered).local()}
            title={dayjs.utc(record?.registered).local().format()}
            format={DATE_TIME_FORMAT}
          />
        </Descriptions.Item>
        <Descriptions.Item label={t("vendor.fields.name")}>
          <TextField value={record?.name} />
        </Descriptions.Item>
        <Descriptions.Item label={t("vendor.fields.comment")}>
          <TextField value={enrichText(record?.comment)} />
        </Descriptions.Item>
        <Descriptions.Item label={t("vendor.fields.empty_spool_weight")}>
          <TextField value={record?.empty_spool_weight} />
        </Descriptions.Item>
        <Descriptions.Item label={t("vendor.fields.external_id")}>
          <TextField value={record?.external_id} />
        </Descriptions.Item>
      </Descriptions>
      <Title level={4} style={{ marginTop: 16 }}>
        {t("settings.extra_fields.tab")}
      </Title>
      {extraFields?.data?.map((field, index) => (
        <ExtraFieldDisplay key={index} field={field} value={record?.extra[field.key]} />
      ))}
    </Show>
  );
};

export default VendorShow;
