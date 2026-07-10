// Static Modal.confirm needs the same React-19 render patch the app applies in index.tsx.
import "@ant-design/v5-patch-for-react-19";
import { useDelete, useList, useShow } from "@refinedev/core";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Modal } from "antd";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IFilament } from "../filaments/model";
import { setSpoolArchived } from "./functions";
import { ISpool } from "./model";
import { SpoolShow } from "./show";

// Mock at the boundaries: refine's data hooks and the API-calling helpers. antd is real,
// so the split Archive/Delete button and Modal.confirm behave exactly as in the app.
// The point under test is the destructive-action wiring: the primary click must only
// ever archive/unarchive — Delete lives in the overflow menu behind a confirmation.
vi.mock("@refinedev/core", () => ({
  useDelete: vi.fn(),
  useInvalidate: () => vi.fn(),
  useShow: vi.fn(),
  useUpdate: () => ({ mutate: vi.fn() }),
  useTranslate: () => (key: string) => key,
  // #100 sibling-spools query — controllable per-test; defaults to empty in beforeEach.
  useList: vi.fn(),
}));
vi.mock("@refinedev/antd", () => ({
  Show: ({
    headerButtons,
    children,
  }: {
    headerButtons: (ctx: { defaultButtons: null }) => React.ReactNode;
    children: React.ReactNode;
  }) => (
    <div>
      {typeof headerButtons === "function" ? headerButtons({ defaultButtons: null }) : headerButtons}
      {children}
    </div>
  ),
  DateField: ({ value }: { value?: unknown }) => <span>{String(value ?? "")}</span>,
  NumberField: ({ value }: { value?: unknown }) => <span>{String(value ?? "")}</span>,
  TextField: ({ value }: { value?: unknown }) => <span>{String(value ?? "")}</span>,
}));
vi.mock("./functions", () => ({
  setSpoolArchived: vi.fn().mockResolvedValue(undefined),
  useSpoolAdjustModal: () => ({ openSpoolAdjustModal: vi.fn(), spoolAdjustModal: null }),
}));
vi.mock("../../utils/queryFields", () => ({
  EntityType: { spool: "spool" },
  useGetFields: () => ({ data: [] }),
}));
vi.mock("../../utils/settings", () => ({
  useCurrencyFormatter: () => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }),
  useUnitScaling: () => false,
}));
vi.mock("../../utils/parsing", () => ({
  enrichText: (value?: string) => value,
  scaleUnitValue: (value: number, unit: string) => ({ value, unit }),
  formatWeight: (value: number) => `${value} g`,
}));
vi.mock("../../utils/queryUsageEvents", () => ({
  useGetSpoolUsageEvents: () => ({ data: [], isLoading: false }),
}));
vi.mock("../../utils/spoolActionLinks", () => ({
  useSpoolActionLinks: () => [],
  buildSpoolActionUrl: () => "",
}));
vi.mock("../../components/extraFields", () => ({ ExtraFieldDisplay: () => null }));
vi.mock("../../components/numberField", () => ({
  NumberFieldUnit: ({ value }: { value?: unknown }) => <span>{String(value ?? "")}</span>,
}));
vi.mock("../../components/spoolIcon", () => ({ default: () => null }));
vi.mock("../../components/nfcBindModal", () => ({ default: () => null }));
vi.mock("../../components/nfcWriteModal", () => ({ default: () => null }));

const mockedUseShow = vi.mocked(useShow);
const mockedUseDelete = vi.mocked(useDelete);
const mockedUseList = vi.mocked(useList);
const mockedSetSpoolArchived = vi.mocked(setSpoolArchived);

function mockSiblings(records: ISpool[]) {
  mockedUseList.mockReturnValue({
    result: { data: records },
    query: { isLoading: false },
  } as unknown as ReturnType<typeof useList>);
}

function filament(): IFilament {
  return { id: 1, registered: "2024-01-01", density: 1.24, diameter: 1.75, extra: {} };
}

function spool(over: Partial<ISpool> = {}): ISpool {
  return {
    id: 42,
    registered: "2024-01-01T00:00:00Z",
    filament: filament(),
    used_weight: 100,
    used_length: 33,
    archived: false,
    extra: {},
    ...over,
  };
}

function renderShow(record: ISpool) {
  mockedUseShow.mockReturnValue({
    query: { data: { data: record }, isLoading: false },
  } as unknown as ReturnType<typeof useShow>);
  return render(
    <MemoryRouter>
      <SpoolShow />
    </MemoryRouter>,
  );
}

describe("SpoolShow split Archive/Delete button", () => {
  const deleteMutate = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockedUseDelete.mockReturnValue({ mutate: deleteMutate } as unknown as ReturnType<typeof useDelete>);
    mockSiblings([]);
  });

  afterEach(() => {
    // Modal.confirm renders into its own root outside the RTL tree; clean it up. The React-19
    // scheduler task this queues is drained by the global afterEach flush in src/test/setup.ts.
    Modal.destroyAll();
  });

  it("primary click on an empty spool archives immediately and never deletes", async () => {
    renderShow(spool({ remaining_weight: 0 }));

    await userEvent.click(screen.getByRole("button", { name: /buttons\.archive/ }));

    expect(mockedSetSpoolArchived).toHaveBeenCalledWith(expect.objectContaining({ id: 42 }), true);
    expect(deleteMutate).not.toHaveBeenCalled();
    // No confirmation dialog of any kind was opened.
    expect(screen.queryByText("buttons.confirm")).not.toBeInTheDocument();
  });

  it("primary click on a non-empty spool asks to archive — not to delete", async () => {
    renderShow(spool({ remaining_weight: 500 }));

    await userEvent.click(screen.getByRole("button", { name: /buttons\.archive/ }));

    // The archive confirmation is up; nothing has mutated yet. (The modal renders the
    // title twice — visible confirm title + aria-label title — so scope the query.)
    expect(
      await screen.findByText("spool.titles.archive", { selector: ".ant-modal-confirm-title" }),
    ).toBeInTheDocument();
    expect(mockedSetSpoolArchived).not.toHaveBeenCalled();
    expect(deleteMutate).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "buttons.archive" }));

    expect(mockedSetSpoolArchived).toHaveBeenCalledWith(expect.objectContaining({ id: 42 }), true);
    expect(deleteMutate).not.toHaveBeenCalled();
  });

  it("primary click on an archived spool unarchives without confirmation", async () => {
    renderShow(spool({ archived: true, remaining_weight: 500 }));

    await userEvent.click(screen.getByRole("button", { name: /buttons\.unArchive/ }));

    expect(mockedSetSpoolArchived).toHaveBeenCalledWith(expect.objectContaining({ id: 42 }), false);
    expect(deleteMutate).not.toHaveBeenCalled();
  });

  it("delete is only reachable via the overflow menu and requires confirmation", async () => {
    renderShow(spool({ remaining_weight: 500 }));

    // Open the split button's overflow (the ellipsis trigger next to Archive).
    const trigger = screen.getByRole("img", { name: "ellipsis" }).closest("button");
    expect(trigger).not.toBeNull();
    await userEvent.click(trigger as HTMLElement);
    await userEvent.click(await screen.findByText("buttons.delete"));

    // Confirmation dialog is up; nothing deleted yet.
    expect(await screen.findByText("buttons.confirm", { selector: ".ant-modal-confirm-title" })).toBeInTheDocument();
    expect(deleteMutate).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "buttons.delete" }));

    expect(deleteMutate).toHaveBeenCalledTimes(1);
    expect(deleteMutate).toHaveBeenCalledWith({ resource: "spool", id: 42 }, expect.anything());
    expect(mockedSetSpoolArchived).not.toHaveBeenCalled();
  });
});

describe("SpoolShow sibling spools (#100)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedUseDelete.mockReturnValue({ mutate: vi.fn() } as unknown as ReturnType<typeof useDelete>);
    mockSiblings([]);
  });

  afterEach(() => {
    Modal.destroyAll();
  });

  it("hides the section when there are no other spools of this filament", () => {
    renderShow(spool());
    expect(screen.queryByText("spool.sibling_spools.title")).not.toBeInTheDocument();
  });

  it("lists sibling spools and links them, excluding the spool being shown", () => {
    // The query returns the whole filament set including the current spool (42); the page must
    // filter 42 out and render only the siblings.
    mockSiblings([spool({ id: 42 }), spool({ id: 7, remaining_weight: 250, location: "Shelf B" })]);
    renderShow(spool({ id: 42 }));

    expect(screen.getByText("spool.sibling_spools.title")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "#7" });
    expect(link).toHaveAttribute("href", "/spool/show/7");
    expect(screen.getByText("Shelf B")).toBeInTheDocument();
    // The current spool must not appear as its own sibling.
    expect(screen.queryByRole("link", { name: "#42" })).not.toBeInTheDocument();
  });
});
