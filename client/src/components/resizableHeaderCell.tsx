import React from "react";

// Smallest width a column can be dragged to, so it never collapses to nothing (#90).
export const MIN_COLUMN_WIDTH = 60;

interface ResizableHeaderCellProps extends React.HTMLAttributes<HTMLTableCellElement> {
  // Supplied via each column's onHeaderCell for resizable data columns; absent for the
  // selection/actions columns, which then render as a plain header cell.
  columnId?: string;
  onResize?: (columnId: string, width: number) => void;
}

/**
 * A table header cell with a drag-to-resize handle at its right edge (#90). The handle lives inside a
 * flexbox next to the normal header content rather than being absolutely positioned, so it never has
 * to override the cell's `position` — which would break antd's sticky header. Dragging updates the
 * column width live via `onResize`; the parent persists it. Non-resizable columns (no columnId) fall
 * back to a plain `<th>`.
 */
export function ResizableHeaderCell({ columnId, onResize, children, ...thProps }: ResizableHeaderCellProps) {
  if (!columnId || !onResize) {
    return <th {...thProps}>{children}</th>;
  }

  const startResize = (e: React.MouseEvent) => {
    // Don't let the mousedown reach the header's sort handler.
    e.preventDefault();
    e.stopPropagation();
    const th = (e.currentTarget as HTMLElement).closest("th");
    const startX = e.clientX;
    const startWidth = th?.offsetWidth ?? MIN_COLUMN_WIDTH;

    const onMove = (ev: MouseEvent) => {
      onResize(columnId, Math.max(MIN_COLUMN_WIDTH, startWidth + (ev.clientX - startX)));
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  return (
    <th {...thProps}>
      <div style={{ display: "flex", alignItems: "center" }}>
        <div style={{ flex: "1 1 auto", minWidth: 0 }}>{children}</div>
        <span
          aria-label="resize-column"
          onMouseDown={startResize}
          onClick={(e) => e.stopPropagation()}
          style={{
            flex: "0 0 auto",
            alignSelf: "stretch",
            width: 8,
            marginRight: -8,
            cursor: "col-resize",
            touchAction: "none",
          }}
        />
      </div>
    </th>
  );
}
