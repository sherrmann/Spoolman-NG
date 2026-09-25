/**
 * A filament's reference photo (#88, #415 step 2): preparing it in the browser, and fetching,
 * uploading and removing it over the photo's own endpoints.
 *
 * The server stores what it is given and does no image processing (Pillow ships no 32-bit ARM
 * wheels), so the browser is where photos get small: fit within MAX_IMAGE_DIMENSION and
 * re-encode as WebP, or JPEG where the browser cannot encode WebP. Re-encoding also bakes in the
 * EXIF rotation and strips the metadata, which on phone photos routinely includes GPS
 * coordinates. Ported from the classic client's `utils/imageTransform.ts` and
 * `components/entityImage.tsx`.
 *
 * A plain `<img src>` cannot carry the bearer token (it lives in localStorage, not a cookie), so
 * a photo is fetched with the token and shown from an object URL. Fetched photos are kept per
 * URL with their ETag and revalidated with If-None-Match, which costs a 304 and no bytes when
 * nothing changed.
 */
import { API_BASE } from '$lib/api/config';
import { handleUnauthorized } from '$lib/api/auth';
import { HttpError } from '$lib/api/http';
import { authHeaders } from '$lib/ng/authToken';

export const MAX_IMAGE_DIMENSION = 1024;

export interface PreparedImage {
	blob: Blob;
	contentType: string;
}

/** Scale (width, height) to fit within max on both axes, keeping the aspect ratio; never upscales. */
export function fitWithin(width: number, height: number, max: number): { width: number; height: number } {
	if (width <= max && height <= max) return { width, height };
	const scale = Math.min(max / width, max / height);
	return {
		width: Math.max(1, Math.round(width * scale)),
		height: Math.max(1, Math.round(height * scale))
	};
}

function canvasToBlob(canvas: HTMLCanvasElement, type: string, quality: number): Promise<Blob | null> {
	return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
}

/** Decode, downscale and re-encode a picked file so it fits the server's size cap. */
export async function prepareImageForUpload(file: File): Promise<PreparedImage> {
	// "from-image" applies the EXIF orientation while drawing, so a portrait phone photo stays
	// upright once re-encoding has dropped the metadata that said to rotate it.
	const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
	try {
		const { width, height } = fitWithin(bitmap.width, bitmap.height, MAX_IMAGE_DIMENSION);
		const canvas = document.createElement('canvas');
		canvas.width = width;
		canvas.height = height;
		const context = canvas.getContext('2d');
		if (!context) throw new Error('Canvas 2D context unavailable');
		context.drawImage(bitmap, 0, 0, width, height);
		// A browser that cannot encode WebP ignores the requested type and encodes PNG, so
		// anything but WebP (or nothing) falls back to JPEG rather than being sent as it is.
		let blob = await canvasToBlob(canvas, 'image/webp', 0.85);
		if (!blob || blob.type !== 'image/webp') blob = await canvasToBlob(canvas, 'image/jpeg', 0.85);
		if (!blob) throw new Error('Image encoding failed');
		return { blob, contentType: blob.type };
	} finally {
		bitmap.close();
	}
}

export function filamentImageUrl(filamentId: string): string {
	return `${API_BASE}/filament/${filamentId}/image`;
}

// Object URLs are revoked only when their entry is replaced or dropped, never when a view
// unmounts, so going back to a filament shows its photo at once while it revalidates.
const cache = new Map<string, { etag: string | null; objectUrl: string }>();

function invalidate(url: string): void {
	const entry = cache.get(url);
	if (entry) {
		URL.revokeObjectURL(entry.objectUrl);
		cache.delete(url);
	}
}

/** The object URL already held for a filament's photo, if any; shown while it revalidates. */
export function cachedFilamentImage(filamentId: string): string | null {
	return cache.get(filamentImageUrl(filamentId))?.objectUrl ?? null;
}

/**
 * The filament's photo as an object URL, or null when it has none. Revalidates a cached copy
 * with If-None-Match. A network failure rejects, so the caller can keep what it shows.
 */
export async function loadFilamentImage(filamentId: string, signal?: AbortSignal): Promise<string | null> {
	const url = filamentImageUrl(filamentId);
	const cached = cache.get(url);
	const headers: Record<string, string> = { ...authHeaders() };
	if (cached?.etag) headers['If-None-Match'] = cached.etag;
	const res = await fetch(url, { headers, signal });
	if (res.status === 304 && cached) return cached.objectUrl;
	if (!res.ok) {
		if (res.status === 401) handleUnauthorized(res, true);
		// Removed on the server, or never there: drop the stale copy.
		invalidate(url);
		return null;
	}
	const objectUrl = URL.createObjectURL(await res.blob());
	invalidate(url);
	cache.set(url, { etag: res.headers.get('etag'), objectUrl });
	return objectUrl;
}

async function failure(res: Response, method: string): Promise<HttpError> {
	if (res.status === 401) handleUnauthorized(res, false);
	let body: Record<string, unknown> | undefined;
	try {
		body = (await res.json()) as Record<string, unknown>;
	} catch {
		/* no body, or not JSON */
	}
	const detail = typeof body?.message === 'string' ? `: ${body.message}` : '';
	return new HttpError(`${method} filament image → ${res.status}${detail}`, res.status, body);
}

/** PUT a prepared photo; resolves to the updated filament as the API returns it. */
export async function uploadFilamentImage(
	filamentId: string,
	image: PreparedImage
): Promise<Record<string, unknown>> {
	const url = filamentImageUrl(filamentId);
	const res = await fetch(url, {
		method: 'PUT',
		body: image.blob,
		headers: { 'Content-Type': image.contentType, ...authHeaders() }
	});
	if (!res.ok) throw await failure(res, 'PUT');
	invalidate(url);
	return (await res.json()) as Record<string, unknown>;
}

/** DELETE the filament's photo; one that is already gone counts as removed. */
export async function deleteFilamentImage(filamentId: string): Promise<void> {
	const url = filamentImageUrl(filamentId);
	const res = await fetch(url, { method: 'DELETE', headers: authHeaders() });
	if (!res.ok && res.status !== 404) throw await failure(res, 'DELETE');
	invalidate(url);
}
