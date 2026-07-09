import {
  EditOutlined,
  EyeOutlined,
  FileOutlined,
  FilterOutlined,
  IdcardOutlined,
  PlusSquareOutlined,
  PrinterOutlined,
} from "@ant-design/icons";
import { List, useTable } from "@refinedev/antd";
import { useInvalidate, useNavigation, useTranslate } from "@refinedev/core";
import { Button, Dropdown, Input, message, Space, Table } from "antd";
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import { Key, useCallback, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import {
  ActionsColumn,
  CustomFieldColumn,
  DateColumn,
  FilteredQueryColumn,
  NumberColumn,
  RichColumn,
  SortedColumn,
  SpoolIconColumn,
} from "../../components/column";
import { ColorSimilarityFilter, ColorSimilarityValue } from "../../components/colorSimilarityFilter";
import { useLiveify } from "../../components/liveify";
import SpoolIcon from "../../components/spoolIcon";
import SwatchDownloadModal from "../../components/swatchDownloadModal";
import { useFilamentBulkEditModal } from "./bulkEdit";
import {
  useSpoolmanArticleNumbers,
  useSpoolmanFilamentNames,
  useSpoolmanMaterials,
  useSpoolmanVendors,
} from "../../components/otherModels";
import { removeUndefined } from "../../utils/filtering";
import { EntityType, useGetFields } from "../../utils/queryFields";
import { TableState, useInitialTableState, useStoreInitialState } from "../../utils/saveload";
import { useCurrencyFormatter, useUnitScaling } from "../../utils/settings";
import { IFilament } from "./model";

dayjs.extend(utc);

interface IFilamentCollapsed extends Omit<IFilament, "vendor"> {
  "vendor.name": string | null;
  // Sort-only virtual column (#113): lets the list sort by colour hue. Never populated on the row
  // (the swatch renders from color_hex/multi_color_hexes); it only names the server sort key.
  color_hue?: number | null;
}

function collapseFilament(element: IFilament): IFilamentCollapsed {
  let vendor_name: string | null;
  if (element.vendor) {
    vendor_name = element.vendor.name;
  } else {
    vendor_name = null;
  }
  return { ...element, "vendor.name": vendor_name };
}

function translateColumnI18nKey(columnName: string): string {
  columnName = columnName.replace(".", "_");
  return `filament.fields.${columnName}`;
}

const namespace = "filamentList-v2";

const allColumns: (keyof IFilamentCollapsed & string)[] = [
  "id",
  "vendor.name",
  "name",
  "material",
  "color_hue",
  "price",
  "density",
  "diameter",
  "weight",
  "spool_count",
  "remaining_weight",
  "spool_weight",
  "article_number",
  "external_id",
  "settings_extruder_temp",
  "settings_bed_temp",
  "registered",
  "comment",
];
// The stock aggregates (#49/#53) ship hidden by default to keep the list uncluttered; users opt in
// via the column picker. The colour swatch column (#113) is likewise opt-in — the name column
// already shows the swatch, so this one exists to sort by hue and ships hidden.
const defaultColumns = allColumns.filter(
  (column_id) =>
    [
      "registered",
      "density",
      "diameter",
      "spool_weight",
      "spool_count",
      "remaining_weight",
      "color_hue",
      "external_id",
    ].indexOf(column_id) === -1,
);

export const FilamentList = () => {
  const t = useTranslate();
  const invalidate = useInvalidate();
  const navigate = useNavigate();
  const extraFields = useGetFields(EntityType.filament);
  const currencyFormatter = useCurrencyFormatter();
  const unitScaling = useUnitScaling();

  const allColumnsWithExtraFields = [...allColumns, ...(extraFields.data?.map((field) => "extra." + field.key) ?? [])];

  // Load initial state
  const initialState = useInitialTableState(namespace);

  // Fetch data from the API
  // To provide the live updates, we use a custom solution (useLiveify) instead of the built-in refine "liveMode" feature.
  // This is because the built-in feature does not call the liveProvider subscriber with a list of IDs, but instead
  // calls it with a list of filters, sorters, etc. This means the server-side has to support this, which is quite hard.
  // Free-text search sent as the server-side `search` query param. Transient (not persisted)
  // so a reload shows the full list. Issue #51.
  const [search, setSearch] = useState("");

  // Colour-similarity filter sent as color_hex + color_similarity_threshold (issue #46).
  const [colorFilter, setColorFilter] = useState<ColorSimilarityValue | undefined>(undefined);

  const { tableProps, sorters, setSorters, filters, setFilters, currentPage, pageSize, setCurrentPage } =
    useTable<IFilamentCollapsed>({
      meta: {
        queryParams: {
          ...(search ? { search } : {}),
          ...(colorFilter
            ? { color_hex: colorFilter.colorHex, color_similarity_threshold: colorFilter.threshold }
            : {}),
        },
      },
      syncWithLocation: false,
      pagination: {
        mode: "server",
        currentPage: initialState.pagination.currentPage,
        pageSize: initialState.pagination.pageSize,
      },
      sorters: {
        mode: "server",
        initial: initialState.sorters,
      },
      filters: {
        mode: "server",
        initial: initialState.filters,
      },
      liveMode: "manual",
      onLiveEvent(event) {
        if (event.type === "created" || event.type === "deleted") {
          // updated is handled by the liveify
          invalidate({
            resource: "filament",
            invalidates: ["list"],
          });
        }
      },
      queryOptions: {
        select(data) {
          return {
            total: data.total,
            data: data.data.map(collapseFilament),
          };
        },
      },
    });

  // Create state for the columns to show
  const [showColumns, setShowColumns] = useState<string[]>(initialState.showColumns ?? defaultColumns);

  // Filament to show the swatch download dialog for
  const [swatchFilament, setSwatchFilament] = useState<IFilamentCollapsed | null>(null);

  // Row selection drives the "Print Labels" toolbar action and the bulk-action bar (#73): with rows
  // selected, printing skips the in-page selector, and a contextual bar offers bulk edit.
  const [selectedRowKeys, setSelectedRowKeys] = useState<Key[]>([]);
  const selectedIds = useMemo(() => selectedRowKeys.map(Number), [selectedRowKeys]);

  const [messageApi, messageContextHolder] = message.useMessage();
  const onBulkApplied = useCallback(() => {
    invalidate({ resource: "filament", invalidates: ["list"] });
    setSelectedRowKeys([]);
  }, [invalidate]);
  const { openBulkEdit, bulkEditModal } = useFilamentBulkEditModal(messageApi, onBulkApplied);

  // Store state in local storage
  const tableState: TableState = {
    sorters,
    filters,
    pagination: { currentPage: currentPage, pageSize },
    showColumns,
  };
  useStoreInitialState(namespace, tableState);

  // Collapse the dataSource to a mutable list
  const queryDataSource: IFilamentCollapsed[] = useMemo(
    () => (tableProps.dataSource || []).map((record) => ({ ...record })),
    [tableProps.dataSource],
  );
  const dataSource = useLiveify("filament", queryDataSource, collapseFilament);

  if (tableProps.pagination) {
    tableProps.pagination.showSizeChanger = true;
  }

  const { editUrl, showUrl, cloneUrl } = useNavigation();
  const filamentAddSpoolUrl = (id: number): string => `/spool/create?filament_id=${id}`;
  const actions = (record: IFilamentCollapsed) => [
    { name: t("buttons.show"), icon: <EyeOutlined />, link: showUrl("filament", record.id) },
    { name: t("buttons.edit"), icon: <EditOutlined />, link: editUrl("filament", record.id) },
    { name: t("buttons.clone"), icon: <PlusSquareOutlined />, link: cloneUrl("filament", record.id) },
    { name: t("filament.buttons.add_spool"), icon: <FileOutlined />, link: filamentAddSpoolUrl(record.id) },
    {
      name: t("filament.buttons.download_swatch"),
      icon: <IdcardOutlined />,
      onClick: () => setSwatchFilament(record),
    },
  ];

  const commonProps = {
    t,
    navigate,
    actions,
    dataSource,
    tableState,
    sorter: true,
  };

  return (
    <List
      headerButtons={({ defaultButtons }) => (
        <>
          <Input.Search
            placeholder={t("buttons.search")}
            allowClear
            defaultValue={search}
            onSearch={(value) => {
              setSearch(value);
              setCurrentPage(1);
            }}
            onChange={(e) => {
              if (e.target.value === "") {
                setSearch("");
                setCurrentPage(1);
              }
            }}
            style={{ width: 200 }}
          />
          <ColorSimilarityFilter
            value={colorFilter}
            onChange={(v) => {
              setColorFilter(v);
              setCurrentPage(1);
            }}
          />
          <Button
            type="primary"
            icon={<PrinterOutlined />}
            onClick={() => {
              if (selectedRowKeys.length > 0) {
                const params = new URLSearchParams();
                selectedRowKeys.forEach((key) => params.append("filaments", String(key)));
                // The selection's job is done once it's in the URL; clear it so it
                // doesn't linger when the user returns from printing.
                setSelectedRowKeys([]);
                navigate(`print?${params.toString()}`);
              } else {
                navigate("print");
              }
            }}
          >
            {t("printing.qrcode.button")}
          </Button>
          <Button
            icon={<FilterOutlined />}
            onClick={() => {
              setFilters([], "replace");
              setSorters([{ field: "id", order: "asc" }]);
              setCurrentPage(1);
            }}
          >
            {t("buttons.clearFilters")}
          </Button>
          <Dropdown
            trigger={["click"]}
            menu={{
              items: allColumnsWithExtraFields.map((column_id) => {
                if (column_id.indexOf("extra.") === 0) {
                  const extraField = extraFields.data?.find((field) => "extra." + field.key === column_id);
                  return {
                    key: column_id,
                    label: extraField?.name ?? column_id,
                  };
                }

                return {
                  key: column_id,
                  label: t(translateColumnI18nKey(column_id)),
                };
              }),
              selectedKeys: showColumns,
              selectable: true,
              multiple: true,
              onDeselect: (keys) => {
                setShowColumns(keys.selectedKeys);
              },
              onSelect: (keys) => {
                setShowColumns(keys.selectedKeys);
              },
            }}
          >
            <Button icon={<EditOutlined />}>{t("buttons.hideColumns")}</Button>
          </Dropdown>
          {defaultButtons}
        </>
      )}
    >
      {messageContextHolder}
      {bulkEditModal}
      {/* Contextual bulk-action bar (#73): only shown while rows are selected. */}
      {selectedRowKeys.length > 0 && (
        <Space className="filament-bulk-actions" style={{ marginBottom: 16 }} wrap>
          <span>{t("filament.bulk.selected", { count: selectedRowKeys.length })}</span>
          <Button icon={<EditOutlined />} onClick={() => openBulkEdit(selectedIds)}>
            {t("filament.bulk.edit")}
          </Button>
          <Button type="text" onClick={() => setSelectedRowKeys([])}>
            {t("filament.bulk.clear_selection")}
          </Button>
        </Space>
      )}
      <Table<IFilamentCollapsed>
        {...tableProps}
        sticky
        tableLayout="auto"
        scroll={{ x: "max-content" }}
        dataSource={dataSource}
        rowKey="id"
        rowSelection={{
          selectedRowKeys,
          onChange: setSelectedRowKeys,
          preserveSelectedRowKeys: true,
        }}
        columns={removeUndefined([
          SortedColumn({
            ...commonProps,
            id: "id",
            i18ncat: "filament",
            width: 70,
          }),
          FilteredQueryColumn({
            ...commonProps,
            id: "vendor.name",
            i18nkey: "filament.fields.vendor_name",
            filterValueQuery: useSpoolmanVendors(),
          }),
          SpoolIconColumn({
            ...commonProps,
            id: "name",
            i18ncat: "filament",
            color: (record: IFilamentCollapsed) =>
              record.multi_color_hexes
                ? {
                    colors: record.multi_color_hexes.split(","),
                    vertical: record.multi_color_direction === "longitudinal",
                  }
                : record.color_hex,
            filterValueQuery: useSpoolmanFilamentNames(),
          }),
          FilteredQueryColumn({
            ...commonProps,
            id: "material",
            i18ncat: "filament",
            filterValueQuery: useSpoolmanMaterials(),
            width: 110,
          }),
          // Opt-in colour column (#113): a swatch that sorts by hue (color_hue). The name column
          // already carries the swatch and the colour-similarity filter (#46) lives in the toolbar,
          // so this column is sort-only.
          SortedColumn({
            ...commonProps,
            id: "color_hue",
            i18nkey: "filament.fields.color_hue",
            align: "center",
            width: 80,
            render: (_, record: IFilamentCollapsed) => (
              <SpoolIcon
                color={
                  record.multi_color_hexes
                    ? {
                        colors: record.multi_color_hexes.split(","),
                        vertical: record.multi_color_direction === "longitudinal",
                      }
                    : record.color_hex
                }
              />
            ),
          }),
          SortedColumn({
            ...commonProps,
            id: "price",
            i18ncat: "filament",
            align: "right",
            width: 80,
            render: (_, obj: IFilamentCollapsed) => {
              if (obj.price === undefined) {
                return "";
              }
              return currencyFormatter.format(obj.price);
            },
          }),
          NumberColumn({
            ...commonProps,
            id: "density",
            i18ncat: "filament",
            unit: "g/cm³",
            maxDecimals: 2,
            width: 100,
          }),
          NumberColumn({
            ...commonProps,
            id: "diameter",
            i18ncat: "filament",
            unit: "mm",
            maxDecimals: 2,
            width: 100,
          }),
          NumberColumn({
            ...commonProps,
            id: "weight",
            i18ncat: "filament",
            unit: "g",
            maxDecimals: 0,
            width: 100,
            autoScale: unitScaling,
          }),
          SortedColumn({
            ...commonProps,
            id: "spool_count",
            i18ncat: "filament",
            align: "right",
            width: 90,
          }),
          NumberColumn({
            ...commonProps,
            id: "remaining_weight",
            i18ncat: "filament",
            unit: "g",
            maxDecimals: 0,
            width: 110,
            autoScale: unitScaling,
          }),
          NumberColumn({
            ...commonProps,
            id: "spool_weight",
            i18ncat: "filament",
            unit: "g",
            maxDecimals: 0,
            width: 100,
            autoScale: unitScaling,
          }),
          FilteredQueryColumn({
            ...commonProps,
            id: "article_number",
            i18ncat: "filament",
            filterValueQuery: useSpoolmanArticleNumbers(),
            width: 130,
          }),
          // External ID (#70): opt-in column, hidden by default.
          SortedColumn({
            ...commonProps,
            id: "external_id",
            i18ncat: "filament",
            width: 130,
          }),
          NumberColumn({
            ...commonProps,
            id: "settings_extruder_temp",
            i18ncat: "filament",
            unit: "°C",
            maxDecimals: 0,
            width: 100,
          }),
          NumberColumn({
            ...commonProps,
            id: "settings_bed_temp",
            i18ncat: "filament",
            unit: "°C",
            maxDecimals: 0,
            width: 100,
          }),
          DateColumn({
            ...commonProps,
            id: "registered",
            i18ncat: "filament",
          }),
          ...(extraFields.data?.map((field) => {
            return CustomFieldColumn({
              ...commonProps,
              field,
            });
          }) ?? []),
          RichColumn({
            ...commonProps,
            id: "comment",
            i18ncat: "filament",
            width: 150,
          }),
          ActionsColumn(t("table.actions"), actions),
        ])}
      />
      <SwatchDownloadModal
        filament={swatchFilament}
        vendorName={swatchFilament?.["vendor.name"] ?? undefined}
        onClose={() => setSwatchFilament(null)}
      />
    </List>
  );
};

export default FilamentList;
