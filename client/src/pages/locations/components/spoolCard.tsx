import { useNavigation, useTranslate, useUpdate } from "@refinedev/core";
import { Button, theme } from "antd";
import type { Identifier, XYCoord } from "dnd-core";
import { DragSourceMonitor, useDrag, useDrop } from "react-dnd";

import { EditOutlined, EyeOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import utc from "dayjs/plugin/utc";
import { useEffect, useRef } from "react";
import { Link } from "react-router";
import SpoolIcon from "../../../components/spoolIcon";
import { formatWeight } from "../../../utils/parsing";
import { ISpool } from "../../spools/model";
import { getSpoolEffectiveColor } from "../../../utils/spoolColor";
import { ItemTypes, SpoolDragItem, useCurrentDraggedSpool } from "../dnd";
import { getDisplayTotalWeight, getWeightColor, getWeightPercentage } from "./spoolCardHelpers";

dayjs.extend(utc);
dayjs.extend(relativeTime);

const { useToken } = theme;

export function SpoolCard({
  index,
  spool,
  moveSpoolOrder,
}: {
  index: number;
  spool: ISpool;
  moveSpoolOrder: (dragIndex: number, hoverIndex: number) => void;
}) {
  const { token } = useToken();
  const t = useTranslate();
  const { showUrl } = useNavigation();

  // Using a global state for this, because the drag handlers are reset when the spool changes location
  const { draggedSpoolId, setDraggedSpoolId } = useCurrentDraggedSpool();

  const { mutate: updateSpool } = useUpdate({
    resource: "spool",
    mutationMode: "optimistic",
    successNotification: false,
  });

  const moveSpoolLocation = (spool_id: number, location: string) => {
    updateSpool({
      id: spool_id,
      values: {
        location: location,
      },
    });
  };

  const ref = useRef<HTMLDivElement>(null);
  const [{ handlerId }, drop] = useDrop<SpoolDragItem, void, { handlerId: Identifier | null }>({
    accept: ItemTypes.SPOOL,
    collect(monitor) {
      return {
        handlerId: monitor.getHandlerId(),
      };
    },
    hover(item, monitor) {
      if (!ref.current || item.spool.id === spool.id) {
        return null;
      }

      if (item.spool.location !== spool.location && spool.location) {
        moveSpoolLocation(item.spool.id, spool.location);
        item.spool.location = spool.location;
        return;
      }

      const dragIndex = item.index;
      const hoverIndex = index;

      // Determine rectangle on screen
      const hoverBoundingRect = ref.current?.getBoundingClientRect();

      // Get horizontal middle
      const hoverMiddleY = (hoverBoundingRect.bottom - hoverBoundingRect.top) / 2;

      // Determine mouse position
      const clientOffset = monitor.getClientOffset();

      // Get pixels to the top
      const hoverClientY = (clientOffset as XYCoord).y - hoverBoundingRect.top;

      // Dragging downwards
      if (dragIndex < hoverIndex && hoverClientY < hoverMiddleY) {
        return;
      }

      // Dragging upwards
      if (dragIndex > hoverIndex && hoverClientY > hoverMiddleY) {
        return;
      }

      // Time to actually perform the action
      moveSpoolOrder(item.spool.id, hoverIndex);

      item.index = hoverIndex;
    },
  });

  const [{ isDragging }, drag] = useDrag({
    type: ItemTypes.SPOOL,
    item: () => {
      return { spool, index };
    },
    collect: (monitor: DragSourceMonitor<{ spool: ISpool; index: number }>) => ({
      isDragging: monitor.isDragging(),
    }),
    end() {
      setDraggedSpoolId(-1);
    },
  });

  useEffect(() => {
    if (isDragging) {
      setDraggedSpoolId(spool.id);
    }
  }, [isDragging]);

  // #74: the spool's own color override wins, else the filament color (black fallback preserves the
  // board card's previous look for colorless spools).
  const colorObj = getSpoolEffectiveColor(spool) ?? "#000000";

  let filament_name: string;
  if (spool.filament.vendor && "name" in spool.filament.vendor) {
    filament_name = `${spool.filament.vendor.name} - ${spool.filament.name}`;
  } else {
    filament_name = spool.filament.name ?? spool.filament.id.toString();
  }

  const weightPct = getWeightPercentage(spool);
  const weightColor = getWeightColor(weightPct);

  const opacity = draggedSpoolId === spool.id ? 0 : 1;
  const style = {
    opacity,
    backgroundColor: token.colorBgContainerDisabled,
  };
  drag(drop(ref));

  function formatSubtitle(spool: ISpool) {
    let str = "";
    if (spool.filament.material) str += spool.filament.material;
    // #124: fall back to the spool's initial_weight when the filament has no nominal weight, so the
    // label matches the progress bar (which already uses that fallback) instead of showing blank.
    const total = getDisplayTotalWeight(spool);
    if (total) {
      const remaining_weight = spool.remaining_weight ?? total;
      str += ` \u00B7 ${formatWeight(remaining_weight, 0)} / ${formatWeight(total, 0)}`;
    }
    if (spool.last_used) {
      const dt = dayjs(spool.last_used);
      str += ` \u00B7 ${dt.fromNow()}`;
    }
    return str;
  }

  return (
    <div className="spool" ref={ref} style={style} data-handler-id={handlerId}>
      <SpoolIcon color={colorObj} />
      <div className="info">
        <div className="title">
          <span>
            #{spool.id} {filament_name}
          </span>
          <div style={{ display: "flex", gap: 2, flexShrink: 0 }}>
            <Link to={`/spool/edit/${spool.id}?return=` + encodeURIComponent(window.location.pathname)}>
              <Button icon={<EditOutlined />} title={t("buttons.edit")} size="small" type="text" />
            </Link>
            <Link to={showUrl("spool", spool.id)}>
              <Button icon={<EyeOutlined />} title={t("buttons.show")} size="small" type="text" />
            </Link>
          </div>
        </div>
        <div
          className="subtitle"
          style={{
            color: token.colorTextSecondary,
          }}
        >
          {formatSubtitle(spool)}
        </div>
        <div className="spool-weight-bar" style={{ backgroundColor: token.colorBgContainerDisabled }}>
          <div
            className="spool-weight-bar-fill"
            style={{
              width: `${weightPct}%`,
              backgroundColor: weightColor,
            }}
          />
        </div>
      </div>
    </div>
  );
}
