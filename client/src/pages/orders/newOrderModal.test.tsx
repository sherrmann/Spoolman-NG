// #324 from-scratch "New order" builder. The pure POST-body shape is covered by
// orderBody.test.ts (buildNewOrderBody); this exercises the modal wiring: the OK button gates on
// having at least one line with a filament chosen, "Add filament" grows the lines editor, and a
// completed line submits a POST /order with that line. Same harness style as
// createOrderModal.test.tsx: refine hooks and useShops mocked, real antd Modal/Form/Select rendered.
import "@ant-design/v5-patch-for-react-19";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { IFilament } from "../filaments/model";
import { NewOrderModal } from "./newOrderModal";

const { createMock } = vi.hoisted(() => ({ createMock: vi.fn() }));

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
  useCreate: () => ({ mutate: createMock, mutation: { isPending: false } }),
  useInvalidate: () => vi.fn(),
}));
vi.mock("./useShops", () => ({
  useShops: () => ({ shops: [], ensureShop: vi.fn() }),
}));
// Trim the picker to a plain label so the option text is predictable, and drop the colour swatch.
vi.mock("../spools/functions", () => ({
  formatFilamentLabel: (name: string) => name,
  filamentColorObj: () => undefined,
}));
vi.mock("../../components/spoolIcon", () => ({ default: () => null }));

const FILAMENTS = [
  { id: 1, name: "PLA", density: 1.24, diameter: 1.75 },
  { id: 2, name: "PETG", density: 1.27, diameter: 1.75 },
] as IFilament[];

describe("NewOrderModal (#324)", () => {
  it("keeps the create button disabled until a filament line is complete, then POSTs that line", async () => {
    const user = userEvent.setup();
    createMock.mockClear();
    render(<NewOrderModal open filaments={FILAMENTS} onClose={() => {}} onSuccess={() => {}} />);

    const okButton = screen.getByRole("button", { name: "orders.create_order" });
    expect(okButton).toBeDisabled();

    // Pick a filament on the single starter line.
    const picker = screen.getByRole("combobox", { name: "spool.fields.filament" });
    await user.click(picker);
    await user.click(await screen.findByText("PETG"));

    expect(okButton).toBeEnabled();

    await user.click(okButton);

    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1));
    const body = createMock.mock.calls[0][0];
    expect(body.resource).toBe("order");
    expect(body.values.lines).toEqual([{ filament_id: 2, quantity: 1 }]);
  });

  it("adds a line when 'Add filament' is clicked", async () => {
    const user = userEvent.setup();
    createMock.mockClear();
    render(<NewOrderModal open filaments={FILAMENTS} onClose={() => {}} onSuccess={() => {}} />);

    // One starter filament picker to begin with (the shop AutoComplete is a separate combobox).
    expect(screen.getAllByRole("combobox", { name: "spool.fields.filament" })).toHaveLength(1);
    // The button's leading + icon contributes "plus" to its accessible name, hence the regex.
    await user.click(screen.getByRole("button", { name: /orders\.add_line/ }));
    expect(screen.getAllByRole("combobox", { name: "spool.fields.filament" })).toHaveLength(2);
  });
});
