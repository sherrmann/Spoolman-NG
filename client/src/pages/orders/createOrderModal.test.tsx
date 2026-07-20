// #298 Task 10 review finding: the reset effect's deps were `[open, rows, form]`, so any parent
// re-render that handed the modal a new-but-equal `rows` array (e.g. a background refetch of the
// filament list while the modal stayed open) re-ran `form.resetFields()`/`setQuantities()` and
// silently wiped whatever the user had already typed. This pins the fix — the effect should only
// (re)initialize on the open:false→true transition, not on every `rows` identity change while
// already open. Same harness style as spoolAdjustModal.test.tsx / bulkWeightUpdate.test.tsx: refine
// hooks and useShops mocked, real antd Modal/Form/Table rendered.
import "@ant-design/v5-patch-for-react-19";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { IFilament } from "../filaments/model";
import { LowStockRow } from "../home/analytics";
import { CreateOrderModal } from "./createOrderModal";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
  useCreate: () => ({ mutate: vi.fn(), mutation: { isPending: false } }),
  useInvalidate: () => vi.fn(),
}));
vi.mock("./useShops", () => ({
  useShops: () => ({ shops: [], ensureShop: vi.fn() }),
}));

/** A fresh LowStockRow each call — same content as any prior call, but new object/array
 * references throughout, mirroring what `computeLowStock` rebuilds on every render (see the
 * `lowStock`/`selectableRows`/`selectedRows` `useMemo`s added to lowstock/index.tsx). */
function makeRow(): LowStockRow {
  const filament = { id: 1, name: "Test Filament", density: 1.24, diameter: 1.75 } as IFilament;
  return { filament, remaining: 100, threshold: 200, reason: "explicit" };
}

/** Host holds `rows` in state and can swap it for an equal-but-new array on demand, standing in
 * for lowstock/index.tsx handing CreateOrderModal a recomputed (but unchanged) selection while
 * `open` itself never toggles — exactly the shape of a background refetch during an open modal. */
function Host() {
  const [rows, setRows] = useState<LowStockRow[]>([makeRow()]);
  return (
    <div>
      <button onClick={() => setRows([makeRow()])}>simulate background refetch</button>
      <CreateOrderModal open rows={rows} onClose={() => {}} onSuccess={() => {}} />
    </div>
  );
}

describe("CreateOrderModal edit persistence across background re-renders (#298 review)", () => {
  it("keeps a typed shop name and quantity after `rows` gets a new but equal reference", async () => {
    const user = userEvent.setup();
    render(<Host />);

    const shopInput = screen.getByRole("combobox");
    await user.type(shopInput, "Acme");
    expect(shopInput).toHaveValue("Acme");

    const qtyInput = screen.getByRole("spinbutton");
    await user.clear(qtyInput);
    await user.type(qtyInput, "5");
    expect(qtyInput).toHaveValue("5");

    // Simulate the parent re-rendering with a recomputed-but-equal `rows` array while the modal
    // stays open — before the fix this re-ran the reset effect and wiped both fields above.
    await user.click(screen.getByText("simulate background refetch"));

    expect(shopInput).toHaveValue("Acme");
    expect(qtyInput).toHaveValue("5");
  });
});
