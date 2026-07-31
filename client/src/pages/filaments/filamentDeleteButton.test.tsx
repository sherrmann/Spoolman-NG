// Modal (antd) needs the same React-19 render patch the app applies in index.tsx.
import "@ant-design/v5-patch-for-react-19";
import { useDelete } from "@refinedev/core";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Modal } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FilamentDeleteButton, getFilamentCascadeSpoolCount } from "./filamentDeleteButton";

// Mock at the boundary: refine's useDelete is controlled per-test below so the mutate() calls and
// their resource/id/meta can be asserted directly; antd (Popconfirm/Modal) is real, so the actual
// two-step escalation (plain popconfirm -> 409 -> cascade dialog) renders and behaves as in the app.
vi.mock("@refinedev/core", () => ({
  useDelete: vi.fn(),
  useTranslate: () => (key: string, params?: Record<string, unknown>) =>
    params ? `${key} ${JSON.stringify(params)}` : key,
}));

const mockedUseDelete = vi.mocked(useDelete);

// Shape of the 409 the server actually sends (spoolman/api/v1/filament.py `delete`, response model
// FilamentCascadeRequired in spoolman/api/v1/models.py): `message` is human prose, `spool_count` is
// the structured integer -- and this is what the axios interceptor in @refinedev/simple-rest hangs
// the parsed JSON body off of (`error.response.data`), verified against the real running server.
function spoolCascadeError(spoolCount: number) {
  return {
    statusCode: 409,
    response: {
      data: {
        message: `Filament 5 still has ${spoolCount} spool(s). Deleting it also permanently deletes those spools and their usage history, and this cannot be undone. Pass cascade=true to proceed.`,
        spool_count: spoolCount,
      },
    },
  };
}

// The sibling "N order line(s) reference it" refusal (#298): a plain Message, no spool_count key
// at all -- cascade cannot fix this one, so it must never trigger the escalation dialog.
function orderLineError() {
  return {
    statusCode: 409,
    response: { data: { message: "Cannot delete filament 5: 2 order line(s) reference it." } },
  };
}

// A 409 that claims to be the spool-cascade shape but whose spool_count is missing or malformed --
// e.g. an older/misbehaving server, or a future response shape. Must never produce a guessed count.
// The message deliberately still contains a real, plausible-looking number (9) distinct from any
// count used elsewhere in this file: if a text-parsing fallback ever creeps back in, it would
// happily extract 9 from this prose and this test would keep passing unless it can actually fail
// that way -- so the message is never number-free like "still has some spool(s)" would be.
function malformedCascadeError(spoolCount: unknown) {
  return {
    statusCode: 409,
    response: {
      data: {
        message: "Filament 5 still has 9 spool(s). Deleting it also permanently deletes those spools...",
        spool_count: spoolCount,
      },
    },
  };
}

describe("getFilamentCascadeSpoolCount", () => {
  it("returns null for a non-409 error", () => {
    expect(getFilamentCascadeSpoolCount({ statusCode: 404, response: { data: { spool_count: 3 } } })).toBeNull();
  });

  it("returns null for the order-line-reference 409 (no spool_count field at all)", () => {
    expect(getFilamentCascadeSpoolCount(orderLineError())).toBeNull();
  });

  it("returns null when there is no error", () => {
    expect(getFilamentCascadeSpoolCount(undefined)).toBeNull();
  });

  it("returns null when spool_count is missing, non-numeric, negative, or non-finite", () => {
    expect(getFilamentCascadeSpoolCount(malformedCascadeError(undefined))).toBeNull();
    expect(getFilamentCascadeSpoolCount(malformedCascadeError("3"))).toBeNull();
    expect(getFilamentCascadeSpoolCount(malformedCascadeError(-1))).toBeNull();
    expect(getFilamentCascadeSpoolCount(malformedCascadeError(Number.NaN))).toBeNull();
  });

  it("reads the structured spool_count directly, never parsing the message", () => {
    expect(getFilamentCascadeSpoolCount(spoolCascadeError(3))).toBe(3);
    expect(getFilamentCascadeSpoolCount(spoolCascadeError(12))).toBe(12);
    // The count must come from the field, not the prose: even a message with a *different* number
    // in it must still yield the field's value, proving there is no text-parsing path left at all.
    expect(
      getFilamentCascadeSpoolCount({
        statusCode: 409,
        response: { data: { message: "totally unrelated wording, no numbers match a regex here", spool_count: 7 } },
      }),
    ).toBe(7);
  });
});

describe("FilamentDeleteButton", () => {
  const deleteMutate = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockedUseDelete.mockReturnValue({
      mutate: deleteMutate,
      mutation: { isPending: false },
    } as unknown as ReturnType<typeof useDelete>);
  });

  afterEach(() => {
    // Modal renders into its own root outside the RTL tree; clean it up between tests.
    Modal.destroyAll();
  });

  async function openSimplePopconfirm() {
    await userEvent.click(screen.getByRole("button", { name: /buttons\.delete/ }));
    await userEvent.click(screen.getByRole("button", { name: "buttons.delete" }));
  }

  it("a no-spool delete uses the simple path and sends no cascade param", async () => {
    const onSuccess = vi.fn();
    deleteMutate.mockImplementation((_params, options) => {
      options.onSuccess();
    });

    render(<FilamentDeleteButton filamentId={5} filamentName="Prusament PETG Black" onSuccess={onSuccess} />);
    await openSimplePopconfirm();

    expect(deleteMutate).toHaveBeenCalledTimes(1);
    const [params] = deleteMutate.mock.calls[0];
    expect(params).toMatchObject({ resource: "filament", id: 5 });
    // No cascade query param on the plain delete.
    expect(params.meta).toBeUndefined();
    expect(onSuccess).toHaveBeenCalledTimes(1);
    // The escalation dialog never appears for the simple path.
    expect(screen.queryByText(/filament\.delete_cascade\.title/)).not.toBeInTheDocument();
  });

  it("a 409 opens the cascade dialog showing the server's own structured spool count", async () => {
    deleteMutate.mockImplementation((_params, options) => {
      options.onError(spoolCascadeError(3));
    });

    render(<FilamentDeleteButton filamentId={5} filamentName="Prusament PETG Black" />);
    await openSimplePopconfirm();

    expect(deleteMutate).toHaveBeenCalledTimes(1);
    // The dialog is titled after the filament and quotes the count read from the 409 body's
    // spool_count field -- never a number the client computed itself.
    expect(screen.getByText(/filament\.delete_cascade\.title.*Prusament PETG Black/)).toBeInTheDocument();
    expect(screen.getByText(/filament\.delete_cascade\.spool_count.*"count":3/)).toBeInTheDocument();
    // Confirm button counts the filament itself plus its spools (3 spools + 1 filament = 4).
    expect(screen.getByRole("button", { name: /filament\.delete_cascade\.confirm.*"count":4/ })).toBeInTheDocument();
  });

  it("a 409 that is not the spool-cascade refusal (e.g. order-line reference) does not open the dialog", async () => {
    deleteMutate.mockImplementation((_params, options) => {
      options.onError(orderLineError());
    });

    render(<FilamentDeleteButton filamentId={5} filamentName="Prusament PETG Black" />);
    await openSimplePopconfirm();

    expect(screen.queryByText(/filament\.delete_cascade\.title/)).not.toBeInTheDocument();
  });

  it("a 409 with a missing/malformed spool_count never shows a guessed count", async () => {
    deleteMutate.mockImplementation((_params, options) => {
      options.onError(malformedCascadeError(undefined));
    });

    render(<FilamentDeleteButton filamentId={5} filamentName="Prusament PETG Black" />);
    await openSimplePopconfirm();

    // No dialog with a wrong or absent count -- the failure surfaces as a normal error instead
    // (the default error notification, left to fire since errorNotification returns undefined).
    expect(screen.queryByText(/filament\.delete_cascade\.title/)).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("confirming the cascade dialog re-sends the delete with cascade=true", async () => {
    const onSuccess = vi.fn();
    deleteMutate.mockImplementation((params, options) => {
      if (params.meta?.queryParams?.cascade) {
        options.onSuccess();
      } else {
        options.onError(spoolCascadeError(3));
      }
    });

    render(<FilamentDeleteButton filamentId={5} filamentName="Prusament PETG Black" onSuccess={onSuccess} />);
    await openSimplePopconfirm();

    // Scoped to the dialog: in jsdom the Popconfirm popup has no transitionend event to unmount on,
    // so its own "buttons.delete"/"buttons.cancel" stay in the tree alongside the Modal that just
    // opened. Querying within the modal (role="dialog") avoids matching those stale buttons.
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: /filament\.delete_cascade\.confirm/ }));

    expect(deleteMutate).toHaveBeenCalledTimes(2);
    const [secondParams] = deleteMutate.mock.calls[1];
    expect(secondParams).toMatchObject({ resource: "filament", id: 5, meta: { queryParams: { cascade: true } } });
    expect(onSuccess).toHaveBeenCalledTimes(1);
    // The dialog starts closing after a successful cascade delete (antd's exit animation never
    // completes in jsdom -- no real transitionend -- so this checks the state change rather than
    // waiting for the element to be fully removed).
    expect(screen.getByRole("dialog").className).toMatch(/-leave/);
  });

  it("cancelling the cascade dialog sends nothing further", async () => {
    const onSuccess = vi.fn();
    deleteMutate.mockImplementation((_params, options) => {
      options.onError(spoolCascadeError(3));
    });

    render(<FilamentDeleteButton filamentId={5} filamentName="Prusament PETG Black" onSuccess={onSuccess} />);
    await openSimplePopconfirm();
    expect(deleteMutate).toHaveBeenCalledTimes(1);

    // See the comment above: scope to the modal so the stale Popconfirm "buttons.cancel" isn't hit.
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "buttons.cancel" }));

    // No second request, no success callback, dialog closed.
    expect(deleteMutate).toHaveBeenCalledTimes(1);
    expect(onSuccess).not.toHaveBeenCalled();
    // See the comment above: the dialog is on its way out, not fully removed (jsdom never fires the
    // transitionend antd's exit animation waits for).
    expect(screen.getByRole("dialog").className).toMatch(/-leave/);
  });
});
