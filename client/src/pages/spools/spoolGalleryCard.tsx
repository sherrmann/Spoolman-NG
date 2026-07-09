import { Card, Typography } from "antd";
import SpoolIcon from "../../components/spoolIcon";
import { formatWeight } from "../../utils/parsing";
import { getSpoolEffectiveColor } from "../../utils/spoolColor";
import type { ISpoolCollapsed } from "./list";

const { Text } = Typography;

/**
 * A gallery tile for one spool (#139): a large colour swatch with the filament name and remaining
 * weight below, for picking a spool by colour at a glance. Clicking opens the spool. Read-only — the
 * grid is a browse view; edits still happen in the table/detail.
 */
export function SpoolGalleryCard({ record, onClick }: { record: ISpoolCollapsed; onClick: () => void }) {
  const color = getSpoolEffectiveColor(record);

  return (
    <Card
      hoverable
      size="small"
      onClick={onClick}
      style={record.archived ? { opacity: 0.6 } : undefined}
      styles={{ body: { display: "flex", flexDirection: "column", alignItems: "center", gap: 8, textAlign: "center" } }}
    >
      {/* SpoolIcon sizes in em, so a larger font-size on the wrapper scales the swatch into a tile. */}
      <div style={{ fontSize: 22, lineHeight: 0 }}>
        <SpoolIcon color={color} size="large" no_margin />
      </div>
      <Text strong ellipsis={{ tooltip: record["filament.combined_name"] }} style={{ maxWidth: "100%" }}>
        {record["filament.combined_name"]}
      </Text>
      <Text type="secondary">
        {record.remaining_weight != null ? formatWeight(record.remaining_weight) : ""}
        {record.location ? ` · ${record.location}` : ""}
      </Text>
    </Card>
  );
}
