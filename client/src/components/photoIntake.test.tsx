import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SpoolIntakeExtraction, SpoolIntakeResult } from "../utils/queryAI";

// The intake flow is tested hermetically: the extract mutation and navigation are
// mocked, and the jsdom environment has no createImageBitmap, which exercises the
// downscale fallback (original file, FileReader) for real.

const extractMock = vi.fn();
const navigateMock = vi.fn();

vi.mock("@refinedev/core", () => ({ useTranslate: () => (key: string) => key }));
vi.mock("react-router", () => ({ useNavigate: () => navigateMock }));
vi.mock("../utils/queryAI", () => ({
  useSpoolIntakeExtract: () => ({ mutateAsync: extractMock }),
}));

import { buildHandoffUrl, IntakeReview, PhotoIntakePanel } from "./photoIntake";

const extraction: SpoolIntakeExtraction = {
  vendor: "Prusament",
  name: "Galaxy Black",
  material: "PLA",
  color_hex: null,
  weight_g: 1000,
  spool_weight_g: null,
  diameter_mm: 1.75,
  extruder_temp_c: 215,
  bed_temp_c: null,
  lot_nr: "A123",
  article_number: null,
  confidence: "high",
};

const result: SpoolIntakeResult = {
  extraction,
  matches: {
    library: [
      {
        kind: "library",
        filament_id: 7,
        vendor: "Prusament",
        name: "Galaxy Black",
        material: "PLA",
        match_percent: 97,
      },
    ],
    catalog: [
      {
        kind: "catalog",
        external_id: "prusament_pla_galaxyblack_1000_175",
        vendor: "Prusament",
        name: "Galaxy Black",
        material: "PLA",
        match_percent: 92,
      },
    ],
  },
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("buildHandoffUrl (#361)", () => {
  it("routes a library match to the spool form with the numeric filament preselected", () => {
    const url = buildHandoffUrl("lib:7", extraction);
    expect(url).toBe("/spool/create?from_scan=1&filament_id=7&lot_nr=A123");
  });

  it("routes a catalog match to the spool form with the external id (filament + spool in one save)", () => {
    const url = buildHandoffUrl("cat:prusament_pla_galaxyblack_1000_175", extraction);
    expect(url).toContain("/spool/create?");
    expect(url).toContain("filament_id=prusament_pla_galaxyblack_1000_175");
  });

  it("routes raw extraction to the filament form, carrying only non-null fields", () => {
    const url = buildHandoffUrl("raw", extraction);
    expect(url).toContain("/filament/create?");
    expect(url).toContain("name=Galaxy+Black");
    expect(url).toContain("material=PLA");
    expect(url).toContain("weight=1000");
    expect(url).toContain("extruder_temp=215");
    expect(url).not.toContain("bed_temp=");
    expect(url).not.toContain("color_hex=");
  });
});

describe("IntakeReview (#361)", () => {
  it("defaults to the top library match and navigates to the spool form", async () => {
    const onNavigate = vi.fn();
    const user = userEvent.setup();
    render(<IntakeReview result={result} previewBlob={null} onNavigate={onNavigate} onBack={vi.fn()} />);

    // Library first, then catalog, then the raw fallback.
    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(3);
    expect(radios[0]).toBeChecked();

    await user.click(screen.getByTestId("intake-continue"));
    expect(onNavigate).toHaveBeenCalledWith("/spool/create?from_scan=1&filament_id=7&lot_nr=A123");
  });

  it("shows only non-null extraction fields", () => {
    render(<IntakeReview result={result} previewBlob={null} onNavigate={vi.fn()} onBack={vi.fn()} />);
    expect(screen.getByText("intake.fields.vendor")).toBeInTheDocument();
    expect(screen.queryByText("intake.fields.bed_temp_c")).not.toBeInTheDocument();
  });

  it("falls back to raw extraction when nothing matches", async () => {
    const onNavigate = vi.fn();
    const user = userEvent.setup();
    render(
      <IntakeReview
        result={{ extraction, matches: { library: [], catalog: [] } }}
        previewBlob={null}
        onNavigate={onNavigate}
        onBack={vi.fn()}
      />,
    );

    expect(screen.getAllByRole("radio")).toHaveLength(1);
    await user.click(screen.getByTestId("intake-continue"));
    expect(onNavigate.mock.calls[0][0]).toContain("/filament/create?");
  });
});

describe("PhotoIntakePanel (#361)", () => {
  it("runs pick, extract, review, continue and closes on navigation", async () => {
    extractMock.mockResolvedValue(result);
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<PhotoIntakePanel onClose={onClose} />);

    const file = new File([new Uint8Array([1, 2, 3])], "label.jpg", { type: "image/jpeg" });
    await user.upload(screen.getByTestId("intake-file"), file);

    expect(await screen.findByTestId("intake-review")).toBeInTheDocument();
    expect(extractMock).toHaveBeenCalledTimes(1);
    const payload = extractMock.mock.calls[0][0];
    expect(payload.mime).toBe("image/jpeg");
    expect(typeof payload.image_base64).toBe("string");
    expect(payload.image_base64.length).toBeGreaterThan(0);

    await user.click(screen.getByTestId("intake-continue"));
    expect(onClose).toHaveBeenCalled();
    expect(navigateMock).toHaveBeenCalledWith("/spool/create?from_scan=1&filament_id=7&lot_nr=A123");
  });

  it("surfaces extraction failures and returns to the pick phase", async () => {
    extractMock.mockRejectedValue(new Error("The AI endpoint timed out after 120 s."));
    const user = userEvent.setup();
    render(<PhotoIntakePanel onClose={vi.fn()} />);

    const file = new File([new Uint8Array([1])], "label.jpg", { type: "image/jpeg" });
    await user.upload(screen.getByTestId("intake-file"), file);

    expect(await screen.findByText("The AI endpoint timed out after 120 s.")).toBeInTheDocument();
    expect(screen.getByTestId("intake-pick")).toBeInTheDocument();
  });
});
