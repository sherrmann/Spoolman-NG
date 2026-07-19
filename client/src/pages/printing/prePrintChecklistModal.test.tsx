// #296: the browser print dialog silently breaks label geometry (fit-to-page scaling, wrong
// paper size, driver margins, headers/footers). The pre-print checklist warns at the moment
// it matters. Same harness style as spoolAdjustModal.test.tsx: translate mocked to keys,
// real antd modal.
import "@ant-design/v5-patch-for-react-19";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PrePrintChecklistModal from "./prePrintChecklistModal";

vi.mock("@refinedev/core", () => ({
  // Encode interpolation options into the returned string so size args are assertable.
  useTranslate: () => (key: string, options?: Record<string, unknown>) =>
    options ? `${key}|${JSON.stringify(options)}` : key,
}));

const baseProps = {
  open: true,
  paperWidth: 62,
  paperHeight: 29,
  showPageSizeModeHint: false,
  onApplyPageSizeMode: vi.fn(),
  onCancel: vi.fn(),
  onConfirm: vi.fn(),
};

describe("pre-print checklist modal (#296)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the four checks with the exact paper size interpolated", () => {
    render(<PrePrintChecklistModal {...baseProps} />);
    expect(screen.getByText("printing.generic.checklist.scale")).toBeInTheDocument();
    expect(screen.getByText('printing.generic.checklist.paperSize|{"width":62,"height":29}')).toBeInTheDocument();
    expect(screen.getByText("printing.generic.checklist.margins")).toBeInTheDocument();
    expect(screen.getByText("printing.generic.checklist.headersFooters")).toBeInTheDocument();
  });

  it("hides the page-size-mode hint unless the label/auto mismatch exists", () => {
    render(<PrePrintChecklistModal {...baseProps} />);
    expect(screen.queryByText("printing.generic.checklist.pageSizeModeHint")).not.toBeInTheDocument();
  });

  it("shows the hint with an apply button that fires onApplyPageSizeMode", async () => {
    const user = userEvent.setup();
    render(<PrePrintChecklistModal {...baseProps} showPageSizeModeHint={true} />);
    expect(screen.getByText("printing.generic.checklist.pageSizeModeHint")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "printing.generic.checklist.pageSizeModeApply" }));
    expect(baseProps.onApplyPageSizeMode).toHaveBeenCalledTimes(1);
    expect(baseProps.onConfirm).not.toHaveBeenCalled();
  });

  it("confirms with dontShowAgain=false by default", async () => {
    const user = userEvent.setup();
    render(<PrePrintChecklistModal {...baseProps} />);
    await user.click(screen.getByRole("button", { name: "printing.generic.checklist.printNow" }));
    expect(baseProps.onConfirm).toHaveBeenCalledWith(false);
  });

  it("confirms with dontShowAgain=true when the checkbox is ticked", async () => {
    const user = userEvent.setup();
    render(<PrePrintChecklistModal {...baseProps} />);
    await user.click(screen.getByRole("checkbox", { name: /dontShowAgain/ }));
    await user.click(screen.getByRole("button", { name: "printing.generic.checklist.printNow" }));
    expect(baseProps.onConfirm).toHaveBeenCalledWith(true);
  });

  it("cancel fires onCancel and never confirms", async () => {
    const user = userEvent.setup();
    render(<PrePrintChecklistModal {...baseProps} />);
    await user.click(screen.getByRole("button", { name: "buttons.cancel" }));
    expect(baseProps.onCancel).toHaveBeenCalledTimes(1);
    expect(baseProps.onConfirm).not.toHaveBeenCalled();
  });
});
