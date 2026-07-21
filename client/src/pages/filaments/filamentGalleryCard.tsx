import { Card, Typography } from "antd";
import { filamentImageUrl, useEntityImage } from "../../components/entityImage";
import SpoolIcon from "../../components/spoolIcon";
import { formatWeight } from "../../utils/parsing";
import { filamentColorObj } from "../spools/functions";
import type { IFilamentCollapsed } from "./list";

const { Text } = Typography;

/**
 * A gallery tile for one filament, mirroring the spool gallery (#139): a large colour swatch —
 * or the reference photo when one is attached (#88) — with the name, material and stock
 * aggregates below, for browsing the catalog by colour. Clicking opens the filament.
 * Read-only — edits happen in the table/detail.
 */
export function FilamentGalleryCard({ record, onClick }: { record: IFilamentCollapsed; onClick: () => void }) {
  const color = filamentColorObj(
    record.color_hex,
    record.multi_color_hexes ? record.multi_color_hexes.split(",") : undefined,
    record.multi_color_direction,
  );
  // The colour swatch stays in place until the photo bytes have arrived, so tiles never flash empty.
  const photoSrc = useEntityImage(record.has_image ? filamentImageUrl(record.id) : null);
  const name = record["vendor.name"]
    ? `${record["vendor.name"]} - ${record.name ?? record.id}`
    : (record.name ?? `#${record.id}`);
  const stockParts = [
    record.material ?? "",
    record.spool_count != null && record.spool_count > 0 && record.remaining_weight != null
      ? formatWeight(record.remaining_weight)
      : "",
  ].filter(Boolean);

  return (
    <Card
      hoverable
      size="small"
      onClick={onClick}
      styles={{ body: { display: "flex", flexDirection: "column", alignItems: "center", gap: 8, textAlign: "center" } }}
    >
      {/* SpoolIcon sizes in em, so a larger font-size on the wrapper scales the swatch into a tile. */}
      {photoSrc ? (
        <img src={photoSrc} alt="" style={{ width: "100%", height: 96, objectFit: "cover", borderRadius: 4 }} />
      ) : (
        <div style={{ fontSize: 22, lineHeight: 0 }}>
          <SpoolIcon color={color} size="large" no_margin />
        </div>
      )}
      <Text strong ellipsis={{ tooltip: name }} style={{ maxWidth: "100%" }}>
        {name}
      </Text>
      <Text type="secondary">{stockParts.join(" · ")}</Text>
    </Card>
  );
}
