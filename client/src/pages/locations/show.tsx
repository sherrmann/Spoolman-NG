import { EnvironmentOutlined, PrinterOutlined } from "@ant-design/icons";
import { NumberField, Show, TextField } from "@refinedev/antd";
import { useList, useShow, useTranslate } from "@refinedev/core";
import { Button, Table, Typography } from "antd";
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import { useNavigate, useParams } from "react-router";
import { ExtraFieldDisplay } from "../../components/extraFields";
import { NumberFieldUnit } from "../../components/numberField";
import { enrichText } from "../../utils/parsing";
import { EntityType, useGetFields } from "../../utils/queryFields";
import { useUnitScaling } from "../../utils/settings";
import { IFilament } from "../filaments/model";
import { ISpool } from "../spools/model";
import { ILocation } from "./model";

dayjs.extend(utc);

const { Title } = Typography;

/**
 * Location detail page (#90 / #103). Reached by scanning a location's QR label (the `L-<id>` scheme
 * resolves here) or by deep link. Shows the location's custom fields and — the point of the scan —
 * the spools currently stored there. The board resource is named "locations", which maps straight
 * to the /api/v1/locations entity endpoints, so useShow works without a bespoke fetch.
 */
export const LocationShow = () => {
  const t = useTranslate();
  const navigate = useNavigate();
  const { id } = useParams();
  const extraFields = useGetFields(EntityType.location);
  const unitScaling = useUnitScaling();

  const { query } = useShow<ILocation>({ resource: "locations", id, liveMode: "auto" });
  const { data, isLoading } = query;
  const record = data?.data;

  // Spools currently at this location, matched by name (Spool.location is a plain string). #90.
  const { result: spoolsResult, query: spoolsQuery } = useList<ISpool>({
    resource: "spool",
    pagination: { mode: "off" },
    meta: { queryParams: { allow_archived: false } },
  });
  const spoolsHere = (spoolsResult?.data ?? []).filter((s) => s.location === record?.name);

  const formatFilament = (item: IFilament): string => {
    const vendorPrefix = item.vendor ? `${item.vendor.name} - ` : "";
    const name = item.name ?? `ID: ${item.id}`;
    return `${vendorPrefix}${name}`;
  };

  return (
    <Show
      resource="locations"
      recordItemId={id}
      isLoading={isLoading}
      canEdit={false}
      canDelete={false}
      title={record?.name ?? ""}
      // The board (/locations) is the manager; there are no edit/delete routes for a location, so
      // offer a link back to it plus a label-print action rather than Refine's default buttons.
      headerButtons={() => (
        <>
          <Button
            icon={<PrinterOutlined />}
            disabled={!id}
            onClick={() =>
              navigate(`/location/print?locations=${id}&return=${encodeURIComponent(window.location.pathname)}`)
            }
          >
            {t("locations.print.button")}
          </Button>
          <Button icon={<EnvironmentOutlined />} onClick={() => navigate("/locations")}>
            {t("locations.locations")}
          </Button>
        </>
      )}
    >
      <Title level={5}>{t("locations.show.name")}</Title>
      <TextField value={record?.name} />
      <Title level={5}>{t("locations.show.comment")}</Title>
      <TextField value={enrichText(record?.comment)} />
      <Title level={5}>{t("locations.show.spool_count")}</Title>
      <NumberField value={record?.spool_count ?? spoolsHere.length} />
      {extraFields?.data && extraFields.data.length > 0 && (
        <>
          <Title level={4}>{t("settings.extra_fields.tab")}</Title>
          {extraFields.data.map((field, index) => (
            <ExtraFieldDisplay key={index} field={field} value={record?.extra[field.key]} />
          ))}
        </>
      )}
      <Title level={4}>{t("locations.show.spools_here")}</Title>
      <Table
        size="small"
        rowKey="id"
        loading={spoolsQuery.isLoading}
        dataSource={spoolsHere}
        pagination={false}
        locale={{ emptyText: t("locations.show.no_spools") }}
        columns={[
          {
            title: t("spool.fields.id"),
            dataIndex: "id",
            render: (spoolId: number) => <a href={`/spool/show/${spoolId}`}>#{spoolId}</a>,
          },
          {
            title: t("spool.fields.filament"),
            dataIndex: "filament",
            render: (filament: IFilament) => formatFilament(filament),
          },
          {
            title: t("spool.fields.remaining_weight"),
            dataIndex: "remaining_weight",
            align: "right",
            render: (value?: number) => (
              <NumberFieldUnit
                value={value ?? ""}
                unit="g"
                autoScale={unitScaling}
                options={{ maximumFractionDigits: 1, minimumFractionDigits: 1 }}
              />
            ),
          },
        ]}
      />
    </Show>
  );
};

export default LocationShow;
