import { EditOutlined, HolderOutlined } from "@ant-design/icons";
import { Button, Checkbox, Popover } from "antd";
import { useRef } from "react";
import { DndProvider, useDrag, useDrop, XYCoord } from "react-dnd";
import { HTML5Backend } from "react-dnd-html5-backend";

// A single column entry, shown in the current (effective) order.
export interface ColumnManagerItem {
  id: string;
  label: string;
}

interface Props {
  /** Columns in their current effective order. */
  columns: ColumnManagerItem[];
  /** Ids of the currently-visible columns. */
  visible: string[];
  onVisibleChange: (ids: string[]) => void;
  /** Move the column at `fromIndex` to `toIndex` within the effective order (#94). */
  onReorder: (fromIndex: number, toIndex: number) => void;
  buttonLabel: string;
}

const DND_TYPE = "column-manager-item";

interface DragItem {
  index: number;
}

// One draggable row: a grip handle (the only drag source, so it never fights the checkbox), a
// visibility checkbox and the column label. Reorder uses the vertical-midpoint test so a drag doesn't
// thrash back and forth while hovering a neighbour (mirrors the Locations spool-card DnD).
function DraggableRow({
  item,
  index,
  checked,
  onToggle,
  onReorder,
}: {
  item: ColumnManagerItem;
  index: number;
  checked: boolean;
  onToggle: (id: string, checked: boolean) => void;
  onReorder: (fromIndex: number, toIndex: number) => void;
}) {
  const rowRef = useRef<HTMLDivElement>(null);
  const handleRef = useRef<HTMLSpanElement>(null);

  const [, drop] = useDrop<DragItem>({
    accept: DND_TYPE,
    hover(dragged, monitor) {
      if (!rowRef.current) return;
      const dragIndex = dragged.index;
      const hoverIndex = index;
      if (dragIndex === hoverIndex) return;

      const rect = rowRef.current.getBoundingClientRect();
      const hoverMiddleY = (rect.bottom - rect.top) / 2;
      const clientOffset = monitor.getClientOffset();
      if (!clientOffset) return;
      const hoverClientY = (clientOffset as XYCoord).y - rect.top;

      // Only cross the item once the pointer passes its midpoint, so the swap is stable.
      if (dragIndex < hoverIndex && hoverClientY < hoverMiddleY) return;
      if (dragIndex > hoverIndex && hoverClientY > hoverMiddleY) return;

      onReorder(dragIndex, hoverIndex);
      dragged.index = hoverIndex;
    },
  });

  const [{ isDragging }, drag, preview] = useDrag({
    type: DND_TYPE,
    item: () => ({ index }),
    collect: (monitor) => ({ isDragging: monitor.isDragging() }),
  });

  // Attach react-dnd connectors imperatively to refs (their return type isn't a React ref).
  preview(drop(rowRef));
  drag(handleRef);

  return (
    <div
      ref={rowRef}
      style={{ display: "flex", alignItems: "center", gap: 8, padding: "2px 0", opacity: isDragging ? 0.4 : 1 }}
    >
      <span ref={handleRef} style={{ cursor: "grab", color: "#999", display: "flex" }} aria-label="drag-column">
        <HolderOutlined />
      </span>
      <Checkbox checked={checked} onChange={(e) => onToggle(item.id, e.target.checked)}>
        {item.label}
      </Checkbox>
    </div>
  );
}

/**
 * A "Columns" popover that manages both which columns are shown and their order (#94). Drag the grip
 * to reorder; toggle the checkbox to show/hide. Kept self-contained (its own DndProvider) so it needs
 * no changes to the table's own header rendering.
 */
export function ColumnManager({ columns, visible, onVisibleChange, onReorder, buttonLabel }: Props) {
  const toggle = (id: string, checked: boolean) => {
    onVisibleChange(checked ? [...visible, id] : visible.filter((c) => c !== id));
  };

  const content = (
    <DndProvider backend={HTML5Backend}>
      <div style={{ maxHeight: 420, overflowY: "auto", minWidth: 220 }}>
        {columns.map((item, index) => (
          <DraggableRow
            key={item.id}
            item={item}
            index={index}
            checked={visible.includes(item.id)}
            onToggle={toggle}
            onReorder={onReorder}
          />
        ))}
      </div>
    </DndProvider>
  );

  return (
    <Popover content={content} trigger="click" placement="bottomRight">
      <Button icon={<EditOutlined />}>{buttonLabel}</Button>
    </Popover>
  );
}
