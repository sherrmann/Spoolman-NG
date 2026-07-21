import { useTranslate } from "@refinedev/core";
import { Button, notification } from "antd";
import { useEffect, useRef } from "react";
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

    notification.open({
      key: NOTIFICATION_KEY,
      message: t("update.notification.title"),
      description: t("update.notification.description", { version }),
      duration: 0,
      onClose: remember,
      btn: info.release_url ? (
        <Button
          type="primary"
          size="small"
          href={info.release_url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={() => {
            remember();
            notification.destroy(NOTIFICATION_KEY);
          }}
        >
          {t("update.notification.viewRelease")}
        </Button>
      ) : undefined,
    });
  }, [info?.update_available, info?.latest_version, info?.release_url, t]);

  return null;
};
