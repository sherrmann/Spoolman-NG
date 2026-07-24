import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { NlSearchResult } from "../utils/queryAI";

// The NL-search button is exercised hermetically: the translation endpoint is behind
// useNlSearch, mocked here. What we pin is the #362 contract — invisible unless the toggle
// is on, and that a translation is handed straight to onApply (the list turns it into
// ordinary editable filters).

const settingsMock = vi.fn<() => Record<string, { value: string }> | undefined>();
const mutateAsync = vi.fn<(vars: { query: string; locale: string }) => Promise<NlSearchResult>>();

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
  useGetLocale: () => () => "en",
}));
vi.mock("../utils/querySettings", () => ({ useGetSettings: () => ({ data: settingsMock() }) }));
vi.mock("../utils/queryAI", () => ({
  useNlSearch: () => ({ mutateAsync, isPending: false, isError: false }),
}));

import { NlSearchButton } from "./nlSearchButton";

const RESULT: NlSearchResult = {
  filters: [{ field: "filament.material", values: ["PETG"] }],
  search: "matte",
  color_hex: "000000",
  sort: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  settingsMock.mockReturnValue({ ai_feature_nl_search: { value: "true" } });
  mutateAsync.mockResolvedValue(RESULT);
});

describe("NlSearchButton (#362)", () => {
  it("renders nothing while the feature is disabled", () => {
    settingsMock.mockReturnValue({ ai_feature_nl_search: { value: "false" } });
    render(<NlSearchButton onApply={vi.fn()} />);
    expect(screen.queryByTestId("nl-search-button")).not.toBeInTheDocument();
  });

  it("translates the query and hands the result to onApply", async () => {
    const onApply = vi.fn();
    const user = userEvent.setup();
    render(<NlSearchButton onApply={onApply} />);

    await user.click(screen.getByTestId("nl-search-button"));
    await user.type(screen.getByTestId("nl-search-input"), "matte black petg");
    await user.click(screen.getByRole("button", { name: "spool.nlSearch.search" }));

    expect(mutateAsync).toHaveBeenCalledWith({ query: "matte black petg", locale: "en" });
    expect(onApply).toHaveBeenCalledWith(RESULT);
  });
});
