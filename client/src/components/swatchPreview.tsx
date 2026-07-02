import { useId } from "react";
import { SwatchLayout } from "../utils/swatch";

/** Pixels per mm, so differently sized styles preview at comparable scale. */
const PREVIEW_SCALE = 5;

/** Card outline as an SVG path: rounded rectangle, minus the keychain hole when present. */
function basePathD(layout: SwatchLayout): string {
  const { widthMm: w, heightMm: h } = layout;
  const r = Math.max(0, Math.min(layout.cornerRadiusMm, w / 2, h / 2));
  const rect =
    `M ${r} 0 H ${w - r} A ${r} ${r} 0 0 1 ${w} ${r} V ${h - r} A ${r} ${r} 0 0 1 ${w - r} ${h} ` +
    `H ${r} A ${r} ${r} 0 0 1 0 ${h - r} V ${r} A ${r} ${r} 0 0 1 ${r} 0 Z`;
  if (!layout.hole) return rect;
  const { cx, cy, r: hr } = layout.hole;
  return `${rect} M ${cx + hr} ${cy} A ${hr} ${hr} 0 1 0 ${cx - hr} ${cy} A ${hr} ${hr} 0 1 0 ${cx + hr} ${cy} Z`;
}

/**
 * True-to-scale 2D rendering of a swatch layout: the exact rectangles that
 * become the printed marking, on top of the filament base color.
 */
const SwatchPreview = ({ layout }: { layout: SwatchLayout }) => {
  const gradientId = useId();
  const markingFill = layout.markingColor === "black" ? "#000000" : "#ffffff";
  const baseFill = layout.baseColorHexes.length > 1 ? `url(#${gradientId})` : (layout.baseColorHexes[0] ?? "#d9d9d9");
  return (
    <svg
      viewBox={`0 0 ${layout.widthMm} ${layout.heightMm}`}
      style={{
        width: "100%",
        maxWidth: layout.widthMm * PREVIEW_SCALE,
        height: "auto",
        display: "block",
        margin: "0 auto",
      }}
      role="img"
    >
      {layout.baseColorHexes.length > 1 && (
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="0">
            {layout.baseColorHexes.map((hex, index) => (
              <stop key={index} offset={index / (layout.baseColorHexes.length - 1)} stopColor={hex} />
            ))}
          </linearGradient>
        </defs>
      )}
      <path
        d={basePathD(layout)}
        fillRule="evenodd"
        fill={baseFill}
        stroke="rgba(128, 128, 128, 0.8)"
        strokeWidth={0.3}
      />
      {/* crispEdges only on the marking: it removes anti-aliasing seams between
          adjacent QR rects, but would make the card's round corners jaggy. */}
      <g shapeRendering="crispEdges">
        {layout.markRects.map((rect, index) => (
          <rect key={index} x={rect.x} y={rect.y} width={rect.w} height={rect.h} fill={markingFill} />
        ))}
      </g>
    </svg>
  );
};

export default SwatchPreview;
