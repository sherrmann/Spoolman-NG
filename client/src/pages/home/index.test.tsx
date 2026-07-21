import { useList } from "@refinedev/core";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ColorModeContext } from "../../contexts/color-mode";
import { IFilament } from "../filaments/model";
import { ISpool } from "../spools/model";
import { Home } from "./index";

// Mock at the boundaries: refine's data/i18n/navigation hooks and the settings-backed
// currency formatter. The router is real (MemoryRouter). This lets us drive the four
// render-state branches directly and assert what the USER sees — in particular that the
// error state is distinct from the empty-onboarding state (the bug fixed in PR #3).
vi.mock("@refinedev/core", () => ({
  useList: vi.fn(),
  // Mirrors i18next's dual second argument: a string is a default value, an object is
  // interpolation params (in which case the key itself is the best stand-in).
  useTranslate: () => (key: string, fallback?: unknown) => (typeof fallback === "string" ? fallback : key),
  useNavigation: () => ({ showUrl: (resource: string, id: number) => `/${resource}/show/${id}` }),
  // Used by the Low Stock row's inline ThresholdEdit (#298); not exercised by these
  // render-state tests, so no-op stubs are enough.
  useUpdate: () => ({ mutate: vi.fn() }),
  useInvalidate: () => vi.fn(),
}));
vi.mock("react-i18next", () => ({
  Trans: ({ i18nKey }: { i18nKey: string }) => <span>{i18nKey}</span>,
}));
vi.mock("../../utils/settings", () => ({
  useCurrencyFormatter: () => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }),
  // Matches the shipped default (#298 low-stock redesign) so plain fixture spools/filaments
  // (no explicit low_stock_threshold) are only flagged when a test deliberately drops below it.
  useLowStockFallbackG: () => 200,
}));
// The Usage tab's chart (#81) queries /stats/usage via react-query; stub it so the dashboard
// renders without a QueryClient in these boundary tests.
vi.mock("../../utils/queryStats", () => ({
  useUsageStats: () => ({ data: [], isLoading: false }),
  formatBucketLabel: (period: string) => period,
}));

const mockedUseList = vi.mocked(useList);

function filament(over: Partial<IFilament> = {}): IFilament {
  return { id: 1, registered: "2024-01-01", density: 1.24, diameter: 1.75, extra: {}, ...over };
}

let nextId = 1;
function spool(over: Partial<ISpool> = {}): ISpool {
  const { filament: fil, ...rest } = over;
  return {
    id: nextId++,
    registered: "2024-01-01T00:00:00Z",
    filament: fil ?? filament(),
    used_weight: 0,
    used_length: 0,
    archived: false,
    extra: {},
    ...rest,
  };
}

interface SpoolQueryState {
  data?: ISpool[];
  isLoading?: boolean;
  isError?: boolean;
  refetch?: () => void;
  // Drives the merged per-filament Low Stock tab (#298); defaults to none so plain spool-only
  // tests see no low-stock filaments regardless of the spools' own weights.
  filaments?: IFilament[];
  // Drives the filament query's own loading state. hasLowStock (and the Tabs' default) derives
  // from this query, so the dashboard must gate on it too (#323) — defaults to loaded.
  filamentsLoading?: boolean;
}

function setSpoolQuery({
  data = [],
  isLoading = false,
  isError = false,
  refetch = vi.fn(),
  filaments = [],
  filamentsLoading = false,
}: SpoolQueryState) {
  // useList is called for "spool", "filament", "vendor" and "order"; only the spool query drives
  // the render-state branches. filament supplies both the KPI total and (via its aggregate
  // fields) the Low Stock tab; vendor/order just supply KPI totals / on-order lookups.
  mockedUseList.mockImplementation((opts) => {
    if (opts?.resource === "spool") {
      return { result: { data, total: data.length }, query: { isLoading, isError, refetch } } as unknown as ReturnType<
        typeof useList
      >;
    }
    if (opts?.resource === "filament") {
      return {
        result: { data: filaments, total: filaments.length },
        query: { isLoading: filamentsLoading, isError: false },
      } as unknown as ReturnType<typeof useList>;
    }
    return { result: { total: 0 }, query: { isLoading: false, isError: false } } as unknown as ReturnType<
      typeof useList
    >;
  });
}

function renderHome() {
  return render(
    <MemoryRouter>
      <ColorModeContext.Provider value={{ mode: "dark", preference: "dark", setPreference: () => {} }}>
        <Home />
      </ColorModeContext.Provider>
    </MemoryRouter>,
  );
}

describe("Home render states", () => {
  beforeEach(() => {
    nextId = 1;
    mockedUseList.mockReset();
  });

  it("shows the loading state while spools are loading", () => {
    setSpoolQuery({ isLoading: true });
    renderHome();
    expect(screen.getByText("loading")).toBeInTheDocument();
  });

  // #323: the Tabs' uncontrolled defaultActiveKey reads hasLowStock, which derives from the
  // filament query. If the dashboard mounted once spools finished but filaments were still
  // loading, the tabs would lock in the wrong default. Keep loading until filaments arrive too.
  it("keeps loading while the filament query is still loading, even if spools are ready", () => {
    setSpoolQuery({ data: [spool(), spool()], filamentsLoading: true });
    renderHome();
    expect(screen.getByText("loading")).toBeInTheDocument();
    // The tabs must not have mounted yet — otherwise the uncontrolled default is already locked in.
    expect(screen.queryByRole("tab", { name: /home\.by_material/ })).not.toBeInTheDocument();
  });

  it("shows the error state (not onboarding) and refetches on refresh", async () => {
    const refetch = vi.fn();
    setSpoolQuery({ isError: true, refetch });
    renderHome();

    expect(screen.getByText("Failed to load spools")).toBeInTheDocument();
    // The fixed bug: an error must NOT fall through to the empty-hero onboarding.
    expect(screen.queryByText("home.welcome")).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("buttons.refresh"));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("shows the empty-hero onboarding when there are no spools", () => {
    setSpoolQuery({ data: [] });
    renderHome();
    expect(screen.getByText("home.welcome")).toBeInTheDocument();
    expect(screen.queryByText("Failed to load spools")).not.toBeInTheDocument();
  });

  it("renders the dashboard when spools exist", () => {
    setSpoolQuery({ data: [spool(), spool()] });
    renderHome();
    // The create-action cluster is only present in the populated branch (the page has
    // no redundant "Home" title anymore).
    expect(screen.getByText("buttons.create")).toBeInTheDocument();
    expect(screen.queryByText("home.home")).not.toBeInTheDocument();
    expect(screen.queryByText("home.welcome")).not.toBeInTheDocument();
    expect(screen.queryByText("loading")).not.toBeInTheDocument();
  });
});

// A filament caught by the low-stock gram fallback (#298): no explicit threshold, but its
// aggregate remaining weight has dropped to/below the 200 g default mocked above.
function lowStockFilament(): IFilament {
  return filament({ remaining_weight: 30 });
}

describe("Home dashboard interactions", () => {
  beforeEach(() => {
    nextId = 1;
    mockedUseList.mockReset();
  });

  it("makes each KPI card a link to its resource list", () => {
    setSpoolQuery({ data: [spool()] });
    const { container } = renderHome();
    const hrefs = Array.from(container.querySelectorAll("a.kpi-card")).map((a) => a.getAttribute("href"));
    // Spools, Filaments, Manufacturers, Total Stock (spool-derived) in order.
    expect(hrefs).toEqual(["/spool", "/filament", "/vendor", "/spool"]);
  });

  it("shows no low-stock warning icon and defaults to the material tab when nothing is low", () => {
    setSpoolQuery({ data: [spool(), spool()] });
    renderHome();
    // No warning triangle anywhere (neither the KPI footer nor the tab label).
    expect(screen.queryByLabelText("warning")).not.toBeInTheDocument();
    // By Material is the active tab.
    expect(screen.getByRole("tab", { name: /home\.by_material/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /home\.low_stock/ })).toHaveAttribute("aria-selected", "false");
  });

  it("shows the low-stock warning icon and defaults to the low-stock tab when stock is low", () => {
    setSpoolQuery({ data: [spool(), spool()], filaments: [lowStockFilament()] });
    renderHome();
    // At least one warning triangle is rendered (tab label + KPI footer).
    expect(screen.getAllByLabelText("warning").length).toBeGreaterThan(0);
    expect(screen.getByRole("tab", { name: /home\.low_stock/ })).toHaveAttribute("aria-selected", "true");
  });
});

// #202: the Gathering Dust card surfaces the least-recently-used spools so forgotten
// inventory (moisture risk) is visible from the dashboard.
describe("Gathering Dust card (#202)", () => {
  beforeEach(() => {
    nextId = 1;
    mockedUseList.mockReset();
  });

  it("lists stale spools oldest-first with a never-used badge", () => {
    setSpoolQuery({
      data: [
        spool({ registered: "2023-01-01T00:00:00Z", location: "Shelf A" }), // never used, oldest
        spool({ last_used: "2026-07-01T00:00:00Z", location: "Shelf B" }),
      ],
    });
    renderHome();

    expect(screen.getByText("home.gathering_dust")).toBeInTheDocument();
    expect(screen.getByText(/home\.never_used/)).toBeInTheDocument();
    expect(screen.queryByText("home.no_stale")).not.toBeInTheDocument();
  });

  it("shows the empty state when every spool is depleted", () => {
    setSpoolQuery({ data: [spool({ remaining_weight: 5, initial_weight: 1000, last_used: "2020-01-01T00:00:00Z" })] });
    renderHome();

    expect(screen.getByText("home.no_stale")).toBeInTheDocument();
  });
});
