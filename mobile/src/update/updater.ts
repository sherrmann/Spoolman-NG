// Native side of the in-app updater: talk to GitHub, download the APK, and
// hand it to the Android package installer. Android-only — iOS apps cannot
// self-install, so callers should gate on Platform.OS. The pure parsing and
// version logic lives in src/lib/update.ts (unit-tested).

import * as Application from "expo-application";
import * as FileSystem from "expo-file-system/legacy";
import * as IntentLauncher from "expo-intent-launcher";
import { Platform } from "react-native";

import { isUpdateAvailable, parseLatestRelease, UPDATE_REPO, type LatestRelease, isUnstampedDevVersion } from "../lib/update";

/** The installed app version (Android versionName), or "0.1.0" for dev builds. */
export function getCurrentVersion(): string {
  return Application.nativeApplicationVersion ?? "0.1.0";
}

/** Fetch and parse the latest GitHub release, or null on any failure. */
export async function fetchLatestRelease(): Promise<LatestRelease | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch(`https://api.github.com/repos/${UPDATE_REPO}/releases/latest`, {
      headers: { Accept: "application/vnd.github+json" },
      signal: controller.signal,
    });
    if (!response.ok) {
      return null;
    }
    return parseLatestRelease(await response.json());
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

export interface UpdateInfo {
  currentVersion: string;
  release: LatestRelease;
}

/**
 * Resolve whether a newer release with a downloadable APK exists. Returns null
 * when up to date, when the check fails, or when the newer release has no APK
 * attached. Never throws.
 */
export async function checkForUpdate(): Promise<UpdateInfo | null> {
  if (Platform.OS !== "android") {
    return null;
  }
  const release = await fetchLatestRelease();
  if (!release || !release.apkUrl) {
    return null;
  }
  const currentVersion = getCurrentVersion();
  if (isUnstampedDevVersion(currentVersion)) {
    // Unstamped local dev build - "is 0.1.0 outdated?" is meaningless (#223).
    return null;
  }
  if (!isUpdateAvailable(currentVersion, release.tag)) {
    return null;
  }
  return { currentVersion, release };
}

export type DownloadProgress = (fraction: number) => void;

/**
 * Download the release APK and launch the system installer. The user still
 * confirms the install (and, first time, grants "install unknown apps"). The
 * apkUrl must come from checkForUpdate()/fetchLatestRelease() — a GitHub
 * release asset URL — never from untrusted input.
 */
export async function downloadAndInstallApk(
  apkUrl: string,
  onProgress?: DownloadProgress,
): Promise<void> {
  if (Platform.OS !== "android") {
    throw new Error("In-app updates are only available on Android.");
  }
  const target = `${FileSystem.cacheDirectory}spoolman-companion-update.apk`;
  // A fresh download each time — stale partials must not be installed.
  await FileSystem.deleteAsync(target, { idempotent: true });

  const resumable = FileSystem.createDownloadResumable(
    apkUrl,
    target,
    {},
    onProgress
      ? (p) => {
          const total = p.totalBytesExpectedToWrite;
          if (total > 0) {
            onProgress(p.totalBytesWritten / total);
          }
        }
      : undefined,
  );
  const result = await resumable.downloadAsync();
  if (!result?.uri) {
    throw new Error("Download failed.");
  }

  const contentUri = await FileSystem.getContentUriAsync(result.uri);
  await IntentLauncher.startActivityAsync("android.intent.action.INSTALL_PACKAGE", {
    data: contentUri,
    // FLAG_GRANT_READ_URI_PERMISSION so the installer can read our cache file.
    flags: 1,
    type: "application/vnd.android.package-archive",
  });
}
