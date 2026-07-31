import { DeleteOutlined } from "@ant-design/icons";
import { type BaseKey, type HttpError, useDelete, useTranslate } from "@refinedev/core";
import { Button, Modal, Popconfirm } from "antd";
import { useState } from "react";

// The 409 the server sends when a filament still has spools (spoolman/api/v1/filament.py `delete`)
// carries a structured `spool_count` integer alongside its human-readable `message`
// (spoolman/api/v1/models.py `FilamentCascadeRequired`). Read that field directly. Do NOT fall back
// to parsing the prose if it's missing -- a silent regex fallback is exactly the failure mode this
// replaced: reword the server message (or hit a genuinely different 409, like a future server that
// hasn't shipped the field yet) and the dialog would show a guessed or wrong count with nothing
// failing anywhere. Absence of the field is treated as "this isn't a spool-cascade 409" and falls
// through to the errorNotification callback below instead, which builds its own message from the
// error body (see the comment there for why: Refine's default notification alone would silently
// drop the server's real text), so the user is never left without any explanation, even though the
// one-click escalation dialog can only appear when the structured count is actually present and
// valid.
//
// This also doubles as the discriminator between the two 409 shapes this endpoint can return: the
// sibling "N order line(s) reference it" refusal (#298) is a plain Message with no spool_count at
// all, so its absence here is expected and correct, not an error condition on its own.
interface FilamentCascadeErrorLike {
  statusCode?: number;
  response?: { data?: unknown };
}

export function getFilamentCascadeSpoolCount(error: FilamentCascadeErrorLike | null | undefined): number | null {
  if (!error || error.statusCode !== 409) {
    return null;
  }
  const data = error.response?.data;
  if (!data || typeof data !== "object" || !("spool_count" in data)) {
    return null;
  }
  const value = (data as Record<string, unknown>).spool_count;
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

export interface FilamentDeleteButtonProps {
  filamentId?: BaseKey;
  filamentName?: string;
  onSuccess?: () => void;
  disabled?: boolean;
  hideText?: boolean;
}

/**
 * Filament delete affordance (task 10b). A filament with no spools deletes with today's plain
 * "Are you sure?" popconfirm, in a single request -- no cascade param sent, no extra round trip.
 *
 * A filament that still has spools can't be deleted that way: the server refuses with 409
 * because deleting it would also permanently delete those spools and their usage history. On
 * that 409, this opens an expanded dialog quoting the server's own spool count and, only on
 * confirmation, re-sends the delete with cascade=true. Cancelling sends nothing further. The
 * count is never computed client-side -- it's read from the 409 body's structured `spool_count`
 * field (see getFilamentCascadeSpoolCount above).
 */
export function FilamentDeleteButton({
  filamentId,
  filamentName,
  onSuccess,
  disabled,
  hideText,
}: FilamentDeleteButtonProps) {
  const t = useTranslate();
  const { mutate, mutation } = useDelete();
  const [cascadeSpoolCount, setCascadeSpoolCount] = useState<number | null>(null);
  const [cascadeLoading, setCascadeLoading] = useState(false);

  const busy = mutation.isPending || cascadeLoading;

  const closeCascadeDialog = () => {
    setCascadeSpoolCount(null);
    setCascadeLoading(false);
  };

  const runDelete = (cascade: boolean) => {
    if (filamentId === undefined) {
      return;
    }
    if (cascade) {
      setCascadeLoading(true);
    }
    mutate(
      {
        resource: "filament",
        id: filamentId,
        meta: cascade ? { queryParams: { cascade: true } } : undefined,
        errorNotification: (error: HttpError | undefined) => {
          // Only the plain (non-cascade) attempt can be resolved by our own dialog; suppress the
          // default toast for exactly that case. Every other failure -- the order-line-reference
          // refusal cascade can't fix, a malformed 409, or a failed cascade retry -- must still
          // surface the server's real message. Refine's own default notification puts that text
          // in `description` (built from `error.message`, which the axios interceptor in
          // dataProvider.ts already sets from the server's response body), but
          // notificationProvider.tsx only ever renders `message`, silently dropping `description`.
          // Building an explicit message here (folding the server detail into `message` itself)
          // is what actually gets it in front of the user, instead of relying on a field that is
          // never read.
          if (!cascade && getFilamentCascadeSpoolCount(error) !== null) {
            return false;
          }
          return {
            message: t("notifications.deleteErrorDetail", {
              resource: "filament",
              statusCode: error?.statusCode,
              message: error?.message,
            }),
            type: "error",
          };
        },
      },
      {
        onSuccess: () => {
          closeCascadeDialog();
          onSuccess?.();
        },
        onError: (error) => {
          if (cascade) {
            setCascadeLoading(false);
            return;
          }
          const spoolCount = getFilamentCascadeSpoolCount(error);
          if (spoolCount !== null) {
            setCascadeSpoolCount(spoolCount);
          }
        },
      },
    );
  };

  return (
    <>
      <Popconfirm
        key="delete"
        title={t("buttons.confirm")}
        okText={t("buttons.delete")}
        cancelText={t("buttons.cancel")}
        okButtonProps={{ danger: true, disabled: busy }}
        onConfirm={() => runDelete(false)}
        disabled={disabled}
      >
        <Button danger loading={busy} icon={<DeleteOutlined />} disabled={disabled} title={t("buttons.delete")}>
          {!hideText && t("buttons.delete")}
        </Button>
      </Popconfirm>
      <Modal
        open={cascadeSpoolCount !== null}
        title={t("filament.delete_cascade.title", { name: filamentName ?? "" })}
        okText={t("filament.delete_cascade.confirm", { count: (cascadeSpoolCount ?? 0) + 1 })}
        okButtonProps={{ danger: true, loading: cascadeLoading }}
        cancelText={t("buttons.cancel")}
        onCancel={closeCascadeDialog}
        onOk={() => runDelete(true)}
        width={420}
      >
        <p>{t("filament.delete_cascade.intro")}</p>
        <ul style={{ marginBottom: 12 }}>
          <li>{t("filament.delete_cascade.spool_count", { count: cascadeSpoolCount ?? 0 })}</li>
          <li>{t("filament.delete_cascade.history")}</li>
        </ul>
        <p>{t("filament.delete_cascade.irreversible")}</p>
      </Modal>
    </>
  );
}
