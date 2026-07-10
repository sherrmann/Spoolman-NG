// Persistence for the server profile and API token. Both live in the platform
// keystore (expo-secure-store): the token because it is a credential, the
// profile because it is small and this avoids a second storage dependency.

import * as SecureStore from "expo-secure-store";

import type { ServerProfile } from "./lib/serverProfile";

const PROFILE_KEY = "serverProfile";
const TOKEN_KEY = "apiToken";

export async function loadProfile(): Promise<ServerProfile | null> {
  try {
    const raw = await SecureStore.getItemAsync(PROFILE_KEY);
    if (!raw) {
      return null;
    }
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      typeof (parsed as { baseUrl?: unknown }).baseUrl === "string"
    ) {
      return parsed as ServerProfile;
    }
  } catch {
    /* corrupted or unavailable — treat as unset */
  }
  return null;
}

export async function saveProfile(profile: ServerProfile): Promise<void> {
  await SecureStore.setItemAsync(PROFILE_KEY, JSON.stringify(profile));
}

export async function clearProfile(): Promise<void> {
  await SecureStore.deleteItemAsync(PROFILE_KEY).catch(() => {});
  await SecureStore.deleteItemAsync(TOKEN_KEY).catch(() => {});
}

export async function loadToken(): Promise<string | null> {
  try {
    return await SecureStore.getItemAsync(TOKEN_KEY);
  } catch {
    return null;
  }
}

export async function saveToken(token: string | null): Promise<void> {
  if (token) {
    await SecureStore.setItemAsync(TOKEN_KEY, token);
  } else {
    await SecureStore.deleteItemAsync(TOKEN_KEY).catch(() => {});
  }
}
