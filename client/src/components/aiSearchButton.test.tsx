import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const searchMock = vi.fn();
let nlSearchFeature = "true";

vi.mock("@refinedev/core", () => ({ useTranslate: () => (key: string) => key }));
vi.mock("../utils/queryAI", () => ({
  useAISearch: () => ({ mutateAsync: searchMock, isPending: false }),
}));
vi.mock("../utils/querySettings", () => ({
  useGetSettings: () => ({ data: { ai_feature_nl_search: { value: nlSearchFeature } } }),
}));

import { AISearchButton } from "./aiSearchButton";

beforeEach(() => {
  vi.clearAllMocks();
  nlSearchFeature = "true";
});

describe("AISearchButton (#362)", () => {
  it("renders nothing while the feature is disabled", () => {
    nlSearchFeature = "false";
    const { container } = render(<AISearchButton entity="spool" onApply={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("translates the query and hands the validated filters to the caller", async () => {
    searchMock.mockResolvedValue({
      filters: { materials: ["PLA"], color_hex: "1a1a1a" },
      dropped: ["under 500 g"],
    });
    const onApply = vi.fn();
    const user = userEvent.setup();
    render(<AISearchButton entity="spool" onApply={onApply} />);

    await user.click(screen.getByTestId("ai-search-button"));
    await user.type(await screen.findByTestId("ai-search-input"), "matte black under 500 g{Enter}");

    expect(searchMock).toHaveBeenCalledWith({ entity: "spool", query: "matte black under 500 g" });
    expect(onApply).toHaveBeenCalledWith({ materials: ["PLA"], color_hex: "1a1a1a" }, ["under 500 g"]);
  });

  it("surfaces failures and applies nothing", async () => {
    searchMock.mockRejectedValue(new Error("The AI endpoint returned HTTP 500."));
    const onApply = vi.fn();
    const user = userEvent.setup();
    render(<AISearchButton entity="filament" onApply={onApply} />);

    await user.click(screen.getByTestId("ai-search-button"));
    await user.type(await screen.findByTestId("ai-search-input"), "glow in the dark{Enter}");

    expect(await screen.findByText("The AI endpoint returned HTTP 500.")).toBeInTheDocument();
    expect(onApply).not.toHaveBeenCalled();
  });
});
