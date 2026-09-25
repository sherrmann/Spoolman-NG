/**
 * The server-wide `swatch_style` setting (#415 step 3): the swatch style a filament's 3MF
 * download starts from. Stored as a JSON string; unset (`""`) or a style this build does not
 * know reads as the default style, as in the classic client.
 */
import { getJson } from '$lib/api/http';
import { parseSetting, setSetting, type SettingResponse } from '$lib/api/settings';
import { getSwatchStyle } from '$lib/ng/swatch';

export const SWATCH_STYLE_KEY = 'swatch_style';

/** The effective default style key. Never throws: an unreachable server gives the default. */
export async function loadSwatchStyle(signal?: AbortSignal): Promise<string> {
	try {
		const s = await getJson<SettingResponse>(`/setting/${SWATCH_STYLE_KEY}`, {}, signal);
		return getSwatchStyle(parseSetting<string>(s, '')).key;
	} catch {
		return getSwatchStyle(null).key;
	}
}

export function saveSwatchStyle(key: string): Promise<void> {
	return setSetting(SWATCH_STYLE_KEY, key);
}
