import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FormInstance } from "antd";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  SimilarFilamentMatch,
  SimilarVendorMatch,
  useSimilarFilament,
  useSimilarVendor,
} from "../../utils/querySimilar";

// The page is heavy (image upload, external-catalog import, colour pickers), so everything but
// the piece under test - the inline "new vendor" duplicate-check hint (#125 + duplicate-check AI
// feature) - is mocked at the boundary: refine's data hooks, the two heavier child components
// that reach for i18next's <Trans> and a react-query hook of their own (FilamentImportModal), and
// the settings/currency lookups (also react-query). Everything else (catalogFields, the image
// picker, antd's own Form/Select) stays real.
let capturedForm: FormInstance | undefined;

vi.mock("@refinedev/core", () => ({
  useInvalidate: () => vi.fn(),
  useNavigation: () => ({ showUrl: (_resource: string, id: number) => `/filament/show/${id}` }),
  useTranslate: () => (key: string) => key,
}));
vi.mock("@refinedev/antd", async () => {
  const antdModule = await import("antd");
  return {
    Create: ({
      children,
      headerButtons,
      footerButtons,
    }: {
      children: React.ReactNode;
      headerButtons?: () => React.ReactNode;
      footerButtons?: () => React.ReactNode;
    }) => (
      <div>
        {headerButtons?.()}
        {children}
        {footerButtons?.()}
      </div>
    ),
    useForm: () => {
      const [form] = antdModule.Form.useForm();
      capturedForm = form;
      return {
        form,
        // The real <Form> must be bound to this same instance so the vendor Select's value
        // (set via the "Use" button below) is actually visible on the shared `form`.
        formProps: { form },
        formLoading: false,
        onFinish: vi.fn().mockResolvedValue({ data: { id: 1 } }),
        redirect: vi.fn(),
      };
    },
    useSelect: () => ({
      selectProps: { options: [{ value: 5, label: "Bambu Lab" }] },
    }),
  };
});
vi.mock("../../components/extraFields", () => ({
  ExtraFieldFormItem: () => null,
  ParsedExtras: (values: unknown) => values,
  StringifiedExtras: (values: unknown) => values,
}));
vi.mock("../../components/stickyFooterBar", () => ({
  StickyFooterBar: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("../../components/filamentImportModal", () => ({
  FilamentImportModal: () => null,
}));
vi.mock("../../utils/settings", () => ({
  useCurrency: () => "USD",
  getCurrencySymbol: () => "$",
}));
vi.mock("../../utils/queryFields", () => ({
  EntityType: { filament: "filament" },
  useGetFields: () => ({ data: [] }),
}));
vi.mock("../../utils/querySimilar", () => ({
  useSimilarVendor: vi.fn(),
  useSimilarFilament: vi.fn(),
}));

import { FilamentCreate } from "./create";

const mockedUseSimilarVendor = vi.mocked(useSimilarVendor);
const mockedUseSimilarFilament = vi.mocked(useSimilarFilament);

// Mirrors the real hook's contract closely enough for this page: nothing for an empty query,
// `result` once a name is actually typed. The real hook never returns a match before any typing.
function mockSimilar(result: { exact: SimilarVendorMatch | null; suggestion: SimilarVendorMatch | null }) {
  mockedUseSimilarVendor.mockImplementation((name: string) => (name ? result : { exact: null, suggestion: null }));
}

// Mirrors the real useSimilarFilament's skip rule closely enough for this page: nothing unless
// the draft has a name of at least two characters, `result` otherwise.
function mockSimilarFilament(result: { exact: SimilarFilamentMatch | null; suggestion: SimilarFilamentMatch | null }) {
  mockedUseSimilarFilament.mockImplementation(({ name }) =>
    (name?.trim().length ?? 0) >= 2 ? result : { exact: null, suggestion: null },
  );
}

function renderPage() {
  return render(
    <MemoryRouter>
      <FilamentCreate mode="create" />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  capturedForm = undefined;
  mockSimilar({ exact: null, suggestion: null });
  mockSimilarFilament({ exact: null, suggestion: null });
});

describe("FilamentCreate inline new-vendor duplicate hint (#125)", () => {
  it("selects the matched vendor and clears the new-vendor name when 'Use' is clicked", async () => {
    mockSimilar({ exact: null, suggestion: { id: 5, name: "Bambu Lab", probability: 0.8 } });
    const user = userEvent.setup();
    renderPage();

    // Open the vendor picker's dropdown so its inline "new vendor" input is in the DOM.
    await user.click(screen.getByLabelText("filament.fields.vendor", { selector: "input" }));
    const newVendorInput = await screen.findByPlaceholderText("filament.form.new_vendor_prompt");
    await user.type(newVendorInput, "Bambu");

    expect(screen.getByText("settings.ai.duplicate.suggestion")).toBeInTheDocument();
    const useButton = screen.getByRole("button", { name: "settings.ai.duplicate.use" });
    await user.click(useButton);

    expect(capturedForm?.getFieldValue("vendor_id")).toBe(5);
    expect((newVendorInput as HTMLInputElement).value).toBe("");
  });
});

describe("FilamentCreate duplicate-check hint (server-side)", () => {
  it("shows the exact hint with a link to the matched filament's show page", async () => {
    mockSimilarFilament({ exact: { id: 7, name: "eSUN PLA Black", probability: null }, suggestion: null });
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("filament.fields.name"), "black pla");

    expect(screen.getByText("settings.ai.duplicate.filament_exact")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "settings.ai.duplicate.open" });
    expect(link).toHaveAttribute("href", "/filament/show/7");
  });

  it("shows the suggestion hint with a link to the matched filament's show page", async () => {
    mockSimilarFilament({ exact: null, suggestion: { id: 8, name: "eSUN PLA+ Black", probability: 0.7 } });
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("filament.fields.name"), "black pla");

    expect(screen.getByText("settings.ai.duplicate.filament_suggestion")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "settings.ai.duplicate.open" });
    expect(link).toHaveAttribute("href", "/filament/show/8");
  });

  it("shows no hint when the server finds nothing", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("filament.fields.name"), "acme spool");

    expect(screen.queryByText("settings.ai.duplicate.filament_exact")).not.toBeInTheDocument();
    expect(screen.queryByText("settings.ai.duplicate.filament_suggestion")).not.toBeInTheDocument();
  });
});

describe("FilamentCreate duplicate-check draft: vendor_id vs. vendor_name", () => {
  function lastDraft() {
    const calls = mockedUseSimilarFilament.mock.calls;
    return calls[calls.length - 1][0];
  }

  it("sends vendor_id, not vendor_name, once an existing vendor is selected - even with leftover text in the new-vendor box", async () => {
    const user = userEvent.setup();
    renderPage();

    // Open the vendor picker's dropdown, leave stray text in the inline "new vendor" box without
    // creating it, then pick an existing vendor from the Select instead.
    await user.click(screen.getByLabelText("filament.fields.vendor", { selector: "input" }));
    const newVendorInput = await screen.findByPlaceholderText("filament.form.new_vendor_prompt");
    await user.type(newVendorInput, "Stray Text");
    await user.click(await screen.findByText("Bambu Lab"));

    expect(capturedForm?.getFieldValue("vendor_id")).toBe(5);
    expect(lastDraft()).toMatchObject({ vendor_id: 5, vendor_name: undefined });
  });

  it("sends vendor_name only when no vendor is selected, trimmed of surrounding whitespace", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByLabelText("filament.fields.vendor", { selector: "input" }));
    const newVendorInput = await screen.findByPlaceholderText("filament.form.new_vendor_prompt");
    await user.type(newVendorInput, "  Polymaker  ");

    expect(lastDraft()).toMatchObject({ vendor_id: undefined, vendor_name: "Polymaker" });
  });

  it("sends neither vendor_id nor vendor_name when the new-vendor box holds only spaces", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByLabelText("filament.fields.vendor", { selector: "input" }));
    const newVendorInput = await screen.findByPlaceholderText("filament.form.new_vendor_prompt");
    await user.type(newVendorInput, "   ");

    expect(lastDraft()).toMatchObject({ vendor_id: undefined, vendor_name: undefined });
  });
});
