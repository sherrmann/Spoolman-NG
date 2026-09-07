/**
 * Account management endpoints (`/api/v1/auth/users`, #52). Administrator-only on the server.
 *
 * Kept out of ./api so the rest of that module stays about inventory. Note the update is a
 * PUT with partial semantics: fields left out are left alone, which is how a password is
 * reset without touching the role and vice versa.
 */
import { deleteResource, getJson, postJson, putJson } from '$lib/api/http';
import type { User } from './types';

type Json = Record<string, unknown>;

function mapUser(u: Json): User {
	return { id: Number(u.id), username: String(u.username ?? ''), role: String(u.role ?? '') };
}

export async function listUsers(signal?: AbortSignal): Promise<User[]> {
	return (await getJson<Json[]>('/auth/users', {}, signal)).map(mapUser);
}

export async function createUser(username: string, password: string, role: string): Promise<User> {
	return mapUser(await postJson<Json>('/auth/users', { username, password, role }));
}

export async function updateUser(id: number, body: { password?: string; role?: string }): Promise<User> {
	return mapUser(await putJson<Json>(`/auth/users/${id}`, body));
}

export async function deleteUser(id: number): Promise<void> {
	await deleteResource(`/auth/users/${id}`);
}
