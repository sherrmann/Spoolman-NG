// Native side of the passkey setup assistant: the installed app's identity
// (package name + signing-cert fingerprints) and the assetlinks.json fetch.
// The pure template/verify logic lives in src/lib/assetlinks.ts (unit-tested).

import * as Application from "expo-application";
import { Platform } from "react-native";

import { getSigningCertSha256 } from "../../modules/app-signing";

/** The installed package name (e.g. "app.spoolman.companion"), or null off-Android. */
export function getInstalledPackageName(): string | null {
  return Platform.OS === "android" ? Application.applicationId : null;
}

/**
 * SHA-256 fingerprints of the certs this APK is signed with. Empty when the
 * native module is unavailable (Expo Go, dev client without a rebuild) — the
 * UI then falls back to "released APK" guidance.
 */
export function getInstalledFingerprints(): string[] {
  if (Platform.OS !== "android") {
    return [];
  }
  return getSigningCertSha256();
}

export interface AssetlinksFetchResult {
  /** HTTP status, when a response arrived at all. */
  status?: number;
  contentType?: string;
  /** The URL the fetch ended on — differs from the requested one after redirects. */
  finalUrl?: string;
  /** The parsed JSON body, when the response body parsed as JSON. */
  payload?: unknown;
  /** Human-readable failure when there is no usable payload. */
  error?: string;
}

/** Fetch a /.well-known/assetlinks.json URL. 10s timeout; never throws. */
export async function fetchAssetlinks(url: string): Promise<AssetlinksFetchResult> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch(url, {
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    const meta = {
      status: response.status,
      contentType: response.headers.get("content-type") ?? undefined,
      finalUrl: response.url || undefined,
    };
    if (!response.ok) {
      return { ...meta, error: `The server answered ${response.status} for ${url}.` };
    }
    const body = await response.text();
    try {
      return { ...meta, payload: JSON.parse(body) };
    } catch {
      return { ...meta, error: "The response is not valid JSON." };
    }
  } catch (e) {
    return {
      error:
        `Could not fetch ${url} — ${e instanceof Error ? e.message : String(e)}. ` +
        "If the domain uses a self-signed or private-CA certificate, note that " +
        "Google's passkey verification requires a publicly-trusted certificate.",
    };
  } finally {
    clearTimeout(timer);
  }
}
