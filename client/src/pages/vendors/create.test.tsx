import { useList } from "@refinedev/core";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SimilarVendorMatch, useSimilarVendor } from "../../utils/querySimilar";
import { IVendor } from "./model";

// The page is exercised hermetically: refine's data hooks, the AI duplicate-check hook and the
// heavier form-support components are mocked at the boundary, antd's own Form stays real so the
// local (#82) and server-side duplicate hints wire up through actual field state. What is under
// test is the #82-plus-duplicate-check contract: the server hint only ever appears once the local
// check has not already fired, and it never blocks submission.
vi.mock("@refinedev/core", () => ({
  useList: vi.fn(),
  useNavigation: () => ({ showUrl: (_resource: string, id: number) => `/vendor/show/${id}` }),
  useTranslate: () => (key: string) => key,
}));
vi.mock("@refinedev/antd", async () => {
  const antdModule = await import("antd");
  return {
    Create: ({ children, footerButtons }: { children: React.ReactNode; footerButtons?: () => React.ReactNode }) => (
      <div>
        {children}
        {footerButtons?.()}
      </div>
    ),
    useForm: () => {
      const [form] = antdModule.Form.useForm();
      return {
        form,
        // The real <Form> must be bound to this same instance, or Form.useWatch below never
        // observes what the user types (it would be watching a form React itself created).
        formProps: { form },
        formLoading: false,
        onFinish: vi.fn().mockResolvedValue({ data: { id: 1 } }),
        redirect: vi.fn(),
      };
    },
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
vi.mock("../../utils/queryFields", () => ({
  EntityType: { vendor: "vendor" },
  useGetFields: () => ({ data: [] }),
}));
vi.mock("../../utils/querySimilar", () => ({
  useSimilarVendor: vi.fn(),
}));

import { VendorCreate } from "./create";

const mockedUseList = vi.mocked(useList);
const mockedUseSimilarVendor = vi.mocked(useSimilarVendor);

function withExistingVendors(names: string[]) {
  mockedUseList.mockReturnValue({
    result: { data: names.map((name, index) => ({ id: index + 1, name }) as IVendor) },
  } as unknown as ReturnType<typeof useList>);
}

function renderPage() {
  return render(
    <MemoryRouter>
      <VendorCreate mode="create" />
    </MemoryRouter>,
  );
}

// Mirrors the real hook's contract closely enough for this page: nothing for an empty (or
// suppressed) query, `result` once a name is actually passed through. Without this, the mock
// would return the same fixed match on the very first render (before any typing), which the real
// hook never does — and would spuriously trigger an initial-hint-then-warning transition in the
// #82 suppression test below.
function mockSimilar(result: { exact: SimilarVendorMatch | null; suggestion: SimilarVendorMatch | null }) {
  mockedUseSimilarVendor.mockImplementation((name: string) => (name ? result : { exact: null, suggestion: null }));
}

beforeEach(() => {
  vi.clearAllMocks();
  withExistingVendors([]);
  mockSimilar({ exact: null, suggestion: null });
});

describe("VendorCreate duplicate hint", () => {
  it("shows the exact hint when the server reports an exact match", async () => {
    mockSimilar({ exact: { id: 2, name: "eSUN", probability: null }, suggestion: null });
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("vendor.fields.name"), "esun");

    expect(screen.getByText("settings.ai.duplicate.exact")).toBeInTheDocument();
  });

  it("shows the suggestion hint with a link to the matched vendor's show page", async () => {
    mockSimilar({ exact: null, suggestion: { id: 5, name: "Bambu Lab", probability: 0.8 } });
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("vendor.fields.name"), "bambu");

    expect(screen.getByText("settings.ai.duplicate.suggestion")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Bambu Lab" });
    expect(link).toHaveAttribute("href", "/vendor/show/5");
  });

  it("shows no hint when the server finds nothing", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("vendor.fields.name"), "acme");

    expect(screen.queryByText("settings.ai.duplicate.exact")).not.toBeInTheDocument();
    expect(screen.queryByText("settings.ai.duplicate.suggestion")).not.toBeInTheDocument();
  });

  it("suppresses the server hint and queries with an empty name once the local duplicate warning fires (#82)", async () => {
    withExistingVendors(["Acme"]);
    mockSimilar({ exact: { id: 9, name: "Something Else", probability: null }, suggestion: null });
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("vendor.fields.name"), "acme");

    expect(screen.getByText("vendor.form.duplicate_name_warning")).toBeInTheDocument();
    // Typing through "a", "ac", "acm" briefly showed the (fixed) mocked exact hint before the
    // final keystroke made it an exact local match; give antd's Form.Item help transition a tick
    // to finish removing that leaving node before asserting it is gone.
    await waitFor(() => expect(screen.queryByText("settings.ai.duplicate.exact")).not.toBeInTheDocument());
    expect(screen.queryByText("settings.ai.duplicate.suggestion")).not.toBeInTheDocument();

    const lastCall = mockedUseSimilarVendor.mock.calls.at(-1) as [string, number | undefined] | undefined;
    expect(lastCall?.[0]).toBe("");
  });
});
