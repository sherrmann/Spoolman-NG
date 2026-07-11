// Pure logic for the passkey setup assistant: building the Digital Asset Links
// JSON the user must host, and verifying the copy actually served by their RP
// domain. All I/O (native signing-cert lookup, the fetch) lives in
// src/passkeys/passkeySetup.ts so this stays unit-testable.
//
// Platform rules this encodes (verified against Google docs / the DAL spec):
// the file lives at https://<rp-id-host>/.well-known/assetlinks.json for the
// EXACT WebAuthn RP-ID hostname (no eTLD+1 fallback), redirects are not
// followed, and the Content-Type must be application/json.

/** The relation that delegates credential (passkey) ceremonies to an app. */
export const LOGIN_CREDS_RELATION = "delegate_permission/common.get_login_creds";

/**
 * The app-links relation. Third-party credential providers (Bitwarden checks
 * this one ONLY, via Google's assetlinks:check API) require it for passkeys in
 * non-browser apps — without it Bitwarden says "Passkeys not supported for
 * this app". Google's docs recommend publishing both relations together.
 */
export const HANDLE_ALL_URLS_RELATION = "delegate_permission/common.handle_all_urls";

/**
 * SHA-256 of the key that signs released companion APKs — the fallback shown
 * when the installed cert can't be read natively. Must match
 * RELEASE_CERT_FINGERPRINT in spoolman/assetlinks.py.
 */
export const RELEASED_APK_FINGERPRINT =
  "FA:C6:17:45:DC:09:03:78:6F:B9:ED:E6:2A:96:2B:39:9F:73:48:F0:BB:6F:89:9B:83:32:66:75:91:03:3B:9C";

/** Uppercase and trim a colon-delimited SHA-256 fingerprint for comparison. */
export function normalizeFingerprint(fingerprint: string): string {
  return fingerprint.trim().toUpperCase();
}

/** The exact JSON a user should host for this app: pretty-printed, copy-paste ready. */
export function buildAssetlinksJson(packageName: string, fingerprints: string[]): string {
  return JSON.stringify(
    [
      {
        relation: [HANDLE_ALL_URLS_RELATION, LOGIN_CREDS_RELATION],
        target: {
          namespace: "android_app",
          package_name: packageName,
          sha256_cert_fingerprints: fingerprints.map(normalizeFingerprint),
        },
      },
    ],
    null,
    2,
  );
}

/**
 * Where Android will look for the DAL file, from a bare hostname or any
 * http(s) URL ("auth.example.com", "https://auth.example.com/?rd=…"). Always
 * https — Android ignores plain-http DAL files. Null when unparseable.
 */
export function wellKnownUrl(hostOrUrl: string): string | null {
  let value = hostOrUrl.trim();
  if (!value) {
    return null;
  }
  const scheme = value.match(/^([a-z][a-z0-9+.-]*):\/\//i);
  if (scheme && !/^https?$/i.test(scheme[1])) {
    return null;
  }
  if (scheme) {
    value = value.slice(scheme[0].length);
  }
  const host = value.match(/^[^/?#\s]+/);
  if (!host || !/^[a-z0-9[]/i.test(host[0])) {
    return null;
  }
  return `https://${host[0].toLowerCase()}/.well-known/assetlinks.json`;
}

export interface AssetlinksVerdict {
  ok: boolean;
  /** Human-readable reasons the check failed; empty when ok. */
  problems: string[];
  /** Non-fatal issues worth surfacing even when ok (e.g. provider quirks). */
  warnings: string[];
}

/**
 * Verify a fetched assetlinks.json payload covers this app: some statement
 * must carry the get_login_creds relation for our package, and at least one of
 * the installed APK's signing-cert fingerprints must be listed. When the
 * installed fingerprints are unknown (native lookup unavailable), the
 * fingerprint check is skipped — package coverage is still verified.
 */
export function verifyAssetlinks(
  payload: unknown,
  packageName: string,
  installedFingerprints: string[],
): AssetlinksVerdict {
  if (!Array.isArray(payload)) {
    return {
      ok: false,
      problems: ["The file is not a JSON array of statements — check it against the template above."],
      warnings: [],
    };
  }

  const forPackage = payload.filter(
    (statement): statement is Record<string, unknown> =>
      typeof statement === "object" &&
      statement !== null &&
      typeof (statement as { target?: unknown }).target === "object" &&
      (statement as { target: { package_name?: unknown } }).target !== null &&
      (statement as { target: { package_name?: unknown } }).target.package_name === packageName,
  );
  if (forPackage.length === 0) {
    return {
      ok: false,
      problems: [`No statement targets the app package ${packageName}.`],
      warnings: [],
    };
  }

  const withRelation = forPackage.filter((statement) => {
    const relation = (statement as { relation?: unknown }).relation;
    return Array.isArray(relation) && relation.includes(LOGIN_CREDS_RELATION);
  });
  if (withRelation.length === 0) {
    return {
      ok: false,
      problems: [`The statement for ${packageName} is missing the "${LOGIN_CREDS_RELATION}" relation.`],
      warnings: [],
    };
  }

  // Bitwarden (and historically Google Password Manager) validates the OTHER
  // relation — a file with only get_login_creds fails there with "Passkeys not
  // supported for this app". Non-fatal because providers may accept it.
  const hasHandleAllUrls = withRelation.some((statement) => {
    const relation = (statement as { relation?: unknown }).relation;
    return Array.isArray(relation) && relation.includes(HANDLE_ALL_URLS_RELATION);
  });
  const warnings = hasHandleAllUrls
    ? []
    : [
        `The statement is missing "${HANDLE_ALL_URLS_RELATION}" — third-party passkey providers ` +
          "like Bitwarden require it and will say passkeys are not supported for this app. " +
          "Host both relations (the template above includes both).",
      ];

  const listed = new Set<string>();
  for (const statement of withRelation) {
    const target = (statement as { target: { sha256_cert_fingerprints?: unknown } }).target;
    if (Array.isArray(target.sha256_cert_fingerprints)) {
      for (const fingerprint of target.sha256_cert_fingerprints) {
        if (typeof fingerprint === "string") {
          listed.add(normalizeFingerprint(fingerprint));
        }
      }
    }
  }
  if (listed.size === 0) {
    return {
      ok: false,
      problems: [`The statement for ${packageName} lists no sha256_cert_fingerprints.`],
      warnings,
    };
  }
  if (installedFingerprints.length > 0) {
    const installed = installedFingerprints.map(normalizeFingerprint);
    if (!installed.some((fingerprint) => listed.has(fingerprint))) {
      return {
        ok: false,
        problems: [
          "None of the listed fingerprints match this APK's signing certificate. " +
            `This APK is signed with ${installed.join(" or ")}.`,
        ],
        warnings,
      };
    }
  }
  return { ok: true, problems: [], warnings };
}

export interface ResponseMeta {
  requestedUrl: string;
  /** The URL the fetch ended on — differs from requestedUrl after a redirect. */
  finalUrl?: string;
  contentType?: string;
}

/**
 * Warnings about how the file was served. Google's verifier is stricter than
 * fetch(): it follows no redirects and requires Content-Type application/json,
 * so a file that parses fine here can still fail verification on-device.
 */
export function responseWarnings(meta: ResponseMeta): string[] {
  const warnings: string[] = [];
  if (meta.finalUrl && comparableUrl(meta.finalUrl) !== comparableUrl(meta.requestedUrl)) {
    warnings.push(
      "The request was redirected — Google's verifier does not follow redirects, " +
        `so the file must be served directly at ${meta.requestedUrl}.`,
    );
  }
  const contentType = meta.contentType?.split(";")[0].trim().toLowerCase();
  if (contentType && contentType !== "application/json") {
    warnings.push(
      `The file is served as ${contentType} — Google's verifier requires Content-Type: application/json.`,
    );
  }
  return warnings;
}

/**
 * Normalize a URL for redirect detection so benign differences — host case,
 * an explicit :443, trailing slashes — don't read as a redirect.
 */
function comparableUrl(url: string): string {
  const match = url.match(/^(https?):\/\/([^/?#]+)([^?#]*)/i);
  if (!match) {
    return url.replace(/\/+$/, "");
  }
  const host = match[2].toLowerCase().replace(/:443$/, "");
  return `${match[1].toLowerCase()}://${host}${match[3].replace(/\/+$/, "")}`;
}
