import { useQuery } from "@tanstack/react-query";
import { clearApiToken, setApiToken } from "./apiToken";
import { apiFetch } from "./authReloadHandler";
import { getAPIURL } from "./url";

// Client wiring for optional user accounts (#52). The login token is stored via the same seam as the
// #48 machine token (apiToken.ts), so once stored it is attached to axios, apiFetch and the
// websocket automatically — nothing else needs to know about accounts.

export type Role = "admin" | "readonly";

export interface AuthStatus {
  auth_required: boolean;
  accounts_enabled: boolean;
}

export interface CurrentUser {
  id: number;
  username: string;
  role: Role;
}

export interface User {
  id: number;
  username: string;
  role: Role;
}

async function errorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json();
    return body.detail ?? body.message ?? fallback;
  } catch {
    return fallback;
  }
}

export async function fetchAuthStatus(): Promise<AuthStatus> {
  const response = await apiFetch(`${getAPIURL()}/auth/status`);
  if (!response.ok) {
    throw new Error("Failed to load auth status");
  }
  return response.json();
}

/** Whether authentication is on and accounts (not just the machine token) are in use. */
export function useAuthStatus() {
  return useQuery<AuthStatus>({ queryKey: ["auth", "status"], queryFn: fetchAuthStatus });
}

/** The current principal (from a login token, the machine token, or anonymous admin). */
export function useCurrentUser() {
  return useQuery<CurrentUser>({
    queryKey: ["auth", "me"],
    queryFn: async () => {
      const response = await apiFetch(`${getAPIURL()}/auth/me`);
      if (!response.ok) {
        throw new Error("Failed to load current user");
      }
      return response.json();
    },
  });
}

/** Log in with a username and password, storing the returned token for all transports. */
export async function login(username: string, password: string): Promise<void> {
  const response = await apiFetch(`${getAPIURL()}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response, "Login failed"));
  }
  const data = await response.json();
  setApiToken(data.access_token);
}

/** Clear the stored token and reload so every transport drops it. */
export function logout(): void {
  clearApiToken();
  window.location.reload();
}

export async function listUsers(): Promise<User[]> {
  const response = await apiFetch(`${getAPIURL()}/auth/users`);
  if (!response.ok) {
    throw new Error(await errorMessage(response, "Failed to load users"));
  }
  return response.json();
}

export async function createUser(username: string, password: string, role: Role): Promise<User> {
  const response = await apiFetch(`${getAPIURL()}/auth/users`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, role }),
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response, "Failed to create user"));
  }
  return response.json();
}

export async function updateUser(id: number, changes: { password?: string; role?: Role }): Promise<User> {
  const response = await apiFetch(`${getAPIURL()}/auth/users/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(changes),
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response, "Failed to update user"));
  }
  return response.json();
}

export async function deleteUser(id: number): Promise<void> {
  const response = await apiFetch(`${getAPIURL()}/auth/users/${id}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(await errorMessage(response, "Failed to delete user"));
  }
}
