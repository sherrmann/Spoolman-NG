import { useTranslate } from "@refinedev/core";
import { Button, notification } from "antd";
import { useEffect, useRef } from "react";
import { useUpdateModal } from "../utils/updateAction";
import { useInfo } from "../utils/useInfo";

// Remembers the newest version the user was already told about, so the toast fires at
// most once per release (dismiss it and it stays quiet until an even newer one ships).
const STORAGE_KEY = "spoolman-update-notified";
const NOTIFICATION_KEY = "spoolman-update-available";

/**
 * Fires a subtle, once-per-version toast (#293) when the server's daily check reports a
 * newer release. Renders nothing itself - mount it once (in the header). Dismissing it
 * records the version in localStorage so it isn't naggy.
 */
export const UpdateNotification = () => {
  const t = useTranslate();
  const { data: info } = useInfo();
  const showUpdateModal = useUpdateModal((s) => s.show);
  // Guard against re-opening on every render while the same version is current.
  const shownFor = useRef<string | null>(null);

  useEffect(() => {
    if (!info?.update_available || !info.latest_version) {
      return;
    }
    const version = info.latest_version;
    if (shownFor.current === version) {
      return;
    }

    let dismissed: string | null = null;
    try {
      dismissed = localStorage.getItem(STORAGE_KEY);
    } catch {
      // Private mode / storage disabled - just show it this session.
    }
    if (dismissed === version) {
      return;
    }
    shownFor.current = version;

    const remember = () => {
      try {
        localStorage.setItem(STORAGE_KEY, version);
      } catch {
        // Ignore storage failures - worst case the toast reappears next load.
      }
    };

    // Native installs (with the action gated on) get an "Update" affordance; every other
    // install type gets "How to update". Both open the per-install-type dialog (#294).
    const actionLabel =
      info.install_type === "native" && info.update_action_available
        ? t("update.action.open")
        : t("update.action.howTo");

    notification.open({
      key: NOTIFICATION_KEY,
      message: t("update.notification.title"),
      description: t("update.notification.description", { version }),
      duration: 0,
      onClose: remember,
      btn: (
        <Button
          type="primary"
          size="small"
          onClick={() => {
            remember();
            notification.destroy(NOTIFICATION_KEY);
            showUpdateModal();
          }}
        >
          {actionLabel}
        </Button>
      ),
    });
  }, [
    info?.update_available,
    info?.latest_version,
    info?.install_type,
    info?.update_action_available,
    showUpdateModal,
    t,
  ]);

  return null;
};
