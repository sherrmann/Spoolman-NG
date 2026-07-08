// Pure helpers for user-defined table column ordering (#94). Kept out of the list page so the logic
// is unit-testable and reusable across tables.

/** The stable id of a built antd column, from its dataIndex (an array path is joined with "."). */
export function columnIdOf(col: { dataIndex?: unknown }): string | undefined {
  const di = col.dataIndex;
  if (Array.isArray(di)) return di.join(".");
  return typeof di === "string" ? di : undefined;
}

/**
 * The order actually applied to the table: the saved order with any ids no longer present dropped,
 * followed by any columns the saved order doesn't mention yet (e.g. freshly added extra fields) in
 * their natural position. `undefined` saved order ⇒ the natural order verbatim.
 */
export function computeEffectiveOrder(saved: string[] | undefined, natural: string[]): string[] {
  if (!saved) return natural;
  const known = new Set(natural);
  const inOrder = saved.filter((id) => known.has(id));
  const seen = new Set(inOrder);
  return [...inOrder, ...natural.filter((id) => !seen.has(id))];
}

/**
 * Reorder built columns to match `order`. Columns whose id isn't in `order` (e.g. the actions column,
 * which has no dataIndex) keep their relative position at the end (stable sort).
 */
export function orderColumns<T extends { dataIndex?: unknown }>(cols: T[], order: string[]): T[] {
  const rank = (col: T) => {
    const idx = order.indexOf(columnIdOf(col) ?? "");
    return idx === -1 ? Number.MAX_SAFE_INTEGER : idx;
  };
  return [...cols].sort((a, b) => rank(a) - rank(b));
}

/** Move the item at `fromIndex` to `toIndex`, returning a new array (the drag-reorder primitive). */
export function moveInOrder(order: string[], fromIndex: number, toIndex: number): string[] {
  const next = [...order];
  const [moved] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, moved);
  return next;
}
