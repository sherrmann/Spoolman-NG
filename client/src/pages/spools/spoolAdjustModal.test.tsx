// #227: the adjust dialog must surface a server rejection (e.g. 400 "Initial weight is not
// set." from /measure) instead of closing as if the adjustment was recorded. Same harness as
// bulkWeightUpdate.test.tsx: refine hooks mocked, messageApi injected, real antd modal.
import "@ant-design/v5-patch-for-react-19";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { MessageInstance } from "antd/es/message/interface";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ISpool } from "./model";
import { useSpoolAdjustModal } from "./functions";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
  useInvalidate: () => vi.fn(),
  useSelect: () => ({ options: [] }),
}));
vi.mock("../../utils/url", () => ({ getAPIURL: () => "http://test/api/v1" }));

const messageApi = { success: vi.fn(), error: vi.fn(), info: vi.fn() } as unknown as MessageInstance;

const spool = { id: 7 } as ISpool;

function ModalHarness() {
  const { openSpoolAdjustModal, spoolAdjustModal } = useSpoolAdjustModal(messageApi);
  return (
    <div>
      <button onClick={() => openSpoolAdjustModal(spool)}>open</button>
      {spoolAdjustModal}
    </div>
  );
}

function Host() {
  return (
    <QueryClientProvider client={new QueryClient()}>
      <ModalHarness />
    </QueryClientProvider>
  );
}

async function openAndSubmit(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByText("open"));
  await user.type(screen.getByRole("spinbutton"), "100");
  await user.click(screen.getByRole("button", { name: "OK" }));
}

describe("spool adjust modal error handling (#227)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the server message and stays open when the adjustment fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          ({
            ok: false,
            status: 400,
            json: async () => ({ message: "Initial weight is not set." }),
          }) as unknown as Response,
      ),
    );
    const user = userEvent.setup();
    render(<Host />);

    await openAndSubmit(user);

    await waitFor(() => expect(messageApi.error).toHaveBeenCalledWith("Initial weight is not set."));
    expect(screen.getByText("spool.titles.adjust")).toBeInTheDocument();
  });

  it("closes without an error toast when the adjustment succeeds", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => ({}) }) as unknown as Response),
    );
    const user = userEvent.setup();
    render(<Host />);

    await openAndSubmit(user);

    await waitFor(() => expect(screen.queryByText("spool.titles.adjust")).not.toBeInTheDocument());
    expect(messageApi.error).not.toHaveBeenCalled();
  });
});
