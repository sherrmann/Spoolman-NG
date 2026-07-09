// Static Modal.confirm needs the React-19 render patch the app applies in index.tsx.
import "@ant-design/v5-patch-for-react-19";
import { useUpdate } from "@refinedev/core";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Modal } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QRScannerPanel } from "./qrCodeScanner";

// The camera can't be driven in a unit test, so mock the Scanner to hand us its onScan callback;
// we then feed it scanned payloads to exercise the #84 move flow end to end (capture spool → scan
// location → confirm → PATCH). decideScan's decision table is covered separately in scanMove.test.
const h = vi.hoisted(() => ({ onScan: null as ((codes: { rawValue: string }[]) => void) | null }));

vi.mock("@yudiel/react-qr-scanner", () => ({
  Scanner: ({ onScan, children }: { onScan: (c: { rawValue: string }[]) => void; children?: React.ReactNode }) => {
    h.onScan = onScan;
    return <div data-testid="scanner">{children}</div>;
  },
}));

const navigate = vi.fn();
vi.mock("react-router", () => ({ useNavigate: () => navigate }));

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, params?: Record<string, unknown>) =>
    params ? `${key}:${JSON.stringify(params)}` : key,
  useUpdate: vi.fn(),
}));

const mockedUseUpdate = vi.mocked(useUpdate);

async function scan(raw: string) {
  await act(async () => {
    await h.onScan?.([{ rawValue: raw }]);
  });
}

describe("QRScannerPanel move flow (#84)", () => {
  const updateMutate = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockedUseUpdate.mockReturnValue({ mutate: updateMutate } as unknown as ReturnType<typeof useUpdate>);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => ({ id: 2, name: "Dry Box" }) }) as unknown as Response),
    );
  });

  afterEach(() => {
    Modal.destroyAll();
    vi.unstubAllGlobals();
  });

  it("navigates on a scan in the default (open) mode", async () => {
    render(<QRScannerPanel />);
    await scan("WEB+SPOOLMAN:S-5");
    expect(navigate).toHaveBeenCalledWith("/spool/show/5");
    expect(updateMutate).not.toHaveBeenCalled();
  });

  it("moves the spool: scan spool → scan location → confirm → PATCH location", async () => {
    render(<QRScannerPanel />);

    // Switch to move mode.
    await userEvent.click(screen.getByText("scan.action.move"));

    // First scan captures the spool; the hint advances to "now scan a location".
    await scan("WEB+SPOOLMAN:S-5");
    expect(screen.getByText(/scan\.move\.scan_location/)).toBeInTheDocument();
    expect(updateMutate).not.toHaveBeenCalled();

    // Second scan is a location — it resolves the name and asks to confirm.
    await scan("WEB+SPOOLMAN:L-2");
    const confirm = await screen.findByText(/scan\.move\.confirm_content/);
    expect(confirm).toBeInTheDocument();
    expect(updateMutate).not.toHaveBeenCalled();

    // Confirm → the spool is PATCHed to the scanned location's name.
    await userEvent.click(screen.getByRole("button", { name: "buttons.continue" }));
    expect(updateMutate).toHaveBeenCalledTimes(1);
    expect(updateMutate.mock.calls[0][0]).toMatchObject({
      resource: "spool",
      id: 5,
      values: { location: "Dry Box" },
    });
  });
});
