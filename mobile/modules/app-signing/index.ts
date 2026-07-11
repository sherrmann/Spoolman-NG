// Local Expo module exposing the installed APK's signing-certificate SHA-256
// fingerprints — what a Digital Asset Links file must list for passkeys.
// expo-application offers no PackageManager signature surface, hence this
// module. Android-only; requireOptionalNativeModule keeps JS-only contexts
// (Expo Go, unit tests) working by returning null instead of throwing.

import { requireOptionalNativeModule } from "expo-modules-core";

interface AppSigningModuleType {
  getSigningCertSha256(): string[];
}

const AppSigning = requireOptionalNativeModule<AppSigningModuleType>("AppSigning");

/**
 * Colon-delimited uppercase SHA-256 fingerprints of the certificates this APK
 * is signed with (all of them, including past certs after a key rotation).
 * Empty when the native module is unavailable.
 */
export function getSigningCertSha256(): string[] {
  try {
    return AppSigning?.getSigningCertSha256() ?? [];
  } catch {
    return [];
  }
}
