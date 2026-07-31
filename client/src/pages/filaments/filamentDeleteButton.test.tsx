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
// The interceptor (client/node_modules/@refinedev/simple-rest/src/utils/axios.ts) also copies that
// same `message` up to the error's own top-level `message` field (and `statusCode` from
// `response.status`) -- that top-level field is what HttpError.message actually is by the time
// component code ever sees the error, and what errorNotification below reads.
function spoolCascadeError(spoolCount: number) {
  const message = `Filament 5 still has ${spoolCount} spool(s). Deleting it also permanently deletes those spools and their usage history, and this cannot be undone. Pass cascade=true to proceed.`;
  return {
    statusCode: 409,
    message,
    response: { data: { message, spool_count: spoolCount } },
  };
}

// The sibling "N order line(s) reference it" refusal (#298): a plain Message, no spool_count key
// at all -- cascade cannot fix this one, so it must never trigger the escalation dialog.
function orderLineError() {
  const message = "Cannot delete filament 5: 2 order line(s) reference it.";
  return {
    statusCode: 409,
    message,
    response: { data: { message } },
  };
}

// A 409 that claims to be the spool-cascade shape but whose spool_count is missing or malformed --
// e.g. an older/misbehaving server, or a future response shape. Must never produce a guessed count.
// The message deliberately still contains a real, plausible-looking number (9) distinct from any
// count used elsewhere in this file: if a text-parsing fallback ever creeps back in, it would
// happily extract 9 from this prose and this test would keep passing unless it can actually fail
// that way -- so the message is never number-free like "still has some spool(s)" would be.
function malformedCascadeError(spoolCount: unknown) {
  const message = "Filament 5 still has 9 spool(s). Deleting it also permanently deletes those spools...";
  return {
    statusCode: 409,
    message,
    response: { data: { message, spool_count: spoolCount } },
  };
}

// An auth-layer refusal (e.g. a FastAPI `HTTPException` in front of this endpoint): the body is
// `{"detail": ...}`, not this endpoint's own `{"message": ...}` shape, so the axios interceptor
// (see spoolCascadeError's comment above) has nothing to copy into `error.message` -- it comes out
// `undefined`, same as if the field were dropped entirely.
function authErrorNoMessage() {
  return {
    statusCode: 403,
    message: undefined,
    response: { data: { detail: "Not authenticated" } },
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

    // No dialog with a wrong or absent count -- the failure surfaces as a normal error instead,
    // via the errorNotification callback's own explicit message (see the tests below).
    expect(screen.queryByText(/filament\.delete_cascade\.title/)).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  // --- errorNotification: the server's real message must actually reach the user -----
  //
  // notificationProvider.tsx (client/src/components/notificationProvider.tsx) renders only
  // `message`, never Refine's `description` -- so a bare `return undefined` here (falling back to
  // Refine's default notification, which puts the server's actual text in `description`) would
  // silently drop it. These drive the `errorNotification` callback directly, the only way to prove
  // what it returns; mocking `useDelete` (as every test above does) means `mutate`'s own
  // implementation never calls it on its own.

  it("errorNotification suppresses the default toast when our own dialog can resolve the 409", async () => {
    deleteMutate.mockImplementation(() => {});
    render(<FilamentDeleteButton filamentId={5} filamentName="Prusament PETG Black" />);
    await openSimplePopconfirm();

    const [firstParams] = deleteMutate.mock.calls[0];
    expect(firstParams.errorNotification(spoolCascadeError(3))).toBe(false);
  });

  it("errorNotification builds an explicit message carrying the server's real text for a 409 our dialog can't fix", async () => {
    deleteMutate.mockImplementation(() => {});
    render(<FilamentDeleteButton filamentId={5} filamentName="Prusament PETG Black" />);
    await openSimplePopconfirm();

    const [firstParams] = deleteMutate.mock.calls[0];
    const result = firstParams.errorNotification(orderLineError());

    expect(result).not.toBe(false);
    expect(result.type).toBe("error");
    // The mocked useTranslate (top of file) echoes back the interpolation params as JSON, so the
    // server's real message surviving into the built notification proves it wasn't dropped.
    expect(result.message).toContain("Cannot delete filament 5: 2 order line(s) reference it.");
  });

  it("errorNotification degrades to the plain error text, with no dangling 'undefined', when the error body has no message", async () => {
    deleteMutate.mockImplementation(() => {});
    render(<FilamentDeleteButton filamentId={5} filamentName="Prusament PETG Black" />);
    await openSimplePopconfirm();

    const [firstParams] = deleteMutate.mock.calls[0];
    const result = firstParams.errorNotification(authErrorNoMessage());

    expect(result).not.toBe(false);
    expect(result.type).toBe("error");
    expect(result.message).not.toContain("undefined");
    // Not just an absence of the literal word: the plain "deleteError" key (no {{message}}
    // placeholder at all) must be the one used, proving the fallback branch actually ran rather
    // than "deleteErrorDetail" happening to interpolate an empty value.
    expect(result.message).toBe(
      `notifications.deleteError ${JSON.stringify({ resource: "filament", statusCode: 403 })}`,
    );
  });

  it("a failed cascade retry keeps the dialog open and its own errorNotification still surfaces a real message", async () => {
    // The cascade (cascade=true) attempt itself fails -- e.g. a spool was added to the filament in
    // the window between the first 409 and the user confirming the dialog. Unlike the very first
    // attempt, this failure is never resolved by re-showing the same dialog (there is nothing left
    // to escalate to); it must not be silently swallowed either.
    deleteMutate.mockImplementation((params, options) => {
      if (params.meta?.queryParams?.cascade) {
        options.onError(orderLineError());
      } else {
        options.onError(spoolCascadeError(3));
      }
    });

    render(<FilamentDeleteButton filamentId={5} filamentName="Prusament PETG Black" />);
    await openSimplePopconfirm();

    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: /filament\.delete_cascade\.confirm/ }));

    expect(deleteMutate).toHaveBeenCalledTimes(2);
    // The dialog stays open (onError, unlike onSuccess, never calls closeCascadeDialog) -- a failed
    // retry must not look like nothing happened, but it must also not just vanish.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("dialog").className).not.toMatch(/-leave/);

    const [, secondCallArgs] = deleteMutate.mock.calls;
    const result = secondCallArgs[0].errorNotification(orderLineError());
    expect(result).not.toBe(false);
    expect(result.message).toContain("Cannot delete filament 5: 2 order line(s) reference it.");
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
