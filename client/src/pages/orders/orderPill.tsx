import { Tag } from "antd";
import { Link } from "react-router";

/** Compose the calm on-order pill text: "Ordered · <age> · <shop>" ("today" same-day; shop omitted when unknown). */
export function formatOrderedPill(
  onOrder: { order_id: number; ordered_at: string },
  shopName: string | undefined,
  now: Date = new Date(),
): string {
  const days = Math.floor((now.getTime() - new Date(onOrder.ordered_at).getTime()) / 86_400_000);
  const age = days <= 0 ? "today" : `${days}d`;
  return shopName ? `Ordered · ${age} · ${shopName}` : `Ordered · ${age}`;
}

/** Calm blue pill for an on-order Low Stock row; links through to the order (#298). */
export function OrderedPill({
  onOrder,
  shopName,
  orderHref,
}: {
  onOrder: { order_id: number; ordered_at: string };
  shopName?: string;
  orderHref: string;
}) {
  return (
    <Link to={orderHref} onClick={(e) => e.stopPropagation()}>
      <Tag color="blue" style={{ cursor: "pointer" }}>
        {formatOrderedPill(onOrder, shopName)}
      </Tag>
    </Link>
  );
}
