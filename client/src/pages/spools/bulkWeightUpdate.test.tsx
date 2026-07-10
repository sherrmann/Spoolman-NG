// The weigh-spools dialog (#99) shares the persisted measurement mode with the per-row
// Adjust dialog (#117). These tests pin the observable contract: picking a mode survives
// closing the dialog AND a full remount (page reload) via localStorage — a fresh mount
// must come back with the last-used mode pre-selected, not silently reset to "length".
import "@ant-design/v5-patch-for-react-19";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { MessageInstance } from "antd/es/message/interface";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useBulkWeightUpdateModal } from "./bulkWeightUpdate";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
  useInvalidate: () => vi.fn(),
}));
vi.mock("../../utils/url", () => ({ getAPIURL: () => "http://test/api/v1" }));

const messageApi = { success: vi.fn(), error: vi.fn(), info: vi.fn() } as unknown as MessageInstance;

function Modal() {
  const { openBulkWeightUpdate, bulkWeightUpdateModal } = useBulkWeightUpdateModal(messageApi);
  return (
    <div>
      <button onClick={openBulkWeightUpdate}>open</button>
      {bulkWeightUpdateModal}
    </div>
  );
}

function Host() {
  return (
    <QueryClientProvider client={new QueryClient()}>
      <Modal />
    </QueryClientProvider>
  );
}

const label = (mode: string) =>
  mode === "measured_weight" ? "spool.fields.measured_weight" : `spool.form.measurement_type.${mode}`;
const radio = (mode: string) => screen.getByRole("radio", { name: label(mode) });
// antd's Radio.Button hides the actual input, which user-event refuses to pointer-click;
// clicking the visible label text is what a user does anyway.
const clickRadio = async (user: ReturnType<typeof userEvent.setup>, mode: string) =>
  user.click(screen.getByText(label(mode)));

describe("weigh spools modal measurement type", () => {
  beforeEach(() => {
    localStorage.clear();
    // The dialog fetches a first page of spools when opened; the list can be empty here.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => [] }) as unknown as Response),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("defaults to length and persists a switch to weight into localStorage", async () => {
    const user = userEvent.setup();
    render(<Host />);
    await user.click(screen.getByText("open"));

    expect(radio("length")).toBeChecked();
    await clickRadio(user, "weight");
    expect(radio("weight")).toBeChecked();
    expect(localStorage.getItem("savedStates-spoolAdjust-measurementType")).toBe(JSON.stringify("weight"));
  });

  it("restores the last-used measurement type on a fresh mount (page reload)", async () => {
    const user = userEvent.setup();
    const first = render(<Host />);
    await user.click(screen.getByText("open"));
    await clickRadio(user, "measured_weight");
    first.unmount();

    render(<Host />);
    await user.click(screen.getByText("open"));
    expect(radio("measured_weight")).toBeChecked();
    expect(radio("length")).not.toBeChecked();
  });
});
