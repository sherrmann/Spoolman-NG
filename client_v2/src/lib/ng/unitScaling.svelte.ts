/**
 * The `unit_scaling` server setting (#85), as this client honours it.
 *
 * Upstream's `weightAuto()` in $lib/utils/format always switches to kilograms at 1000 g, and
 * upstream's own browser suite pins that ("1 kg" is the name of a weight preset button). The
 * React client reads the same setting the other way round: its default is raw grams and the
 * setting turns scaling ON. Reconciling the two strictly would change what every Svelte user
 * sees today and fail the vendored suite, so the rule here is:
 *
 *   - the setting has never been set  -> keep scaling (upstream's behaviour)
 *   - set to true                     -> scale
 *   - set to false                    -> raw grams everywhere
 *
 * The flag is reactive state rather than a plain variable, and that is load-bearing. It is
 * read inside `weightAuto()`, which every weight on screen goes through from a `$derived` or a
 * template, so those re-render when the answer arrives -- the setting is fetched at startup in
 * parallel with the inventory, and a plain variable left whichever rows rendered first showing
 * kilograms next to an inspector showing grams. The same mechanism is what lets the settings
 * page toggle take effect without a reload.
 */
import { getJson } from '$lib/api/http';
import { parseSetting, type SettingResponse } from '$lib/api/settings';

let scaling = $state(true);

/** What the setting means for display, given the server's answer (or none at all). */
export function effectiveUnitScaling(setting: SettingResponse | undefined): boolean {
	if (!setting || !setting.is_set) return true;
	return parseSetting<unknown>(setting, true) !== false;
}

/** Whether large weights should be shown in kilograms right now. */
export function isUnitScaling(): boolean {
	return scaling;
}

export function setUnitScaling(value: boolean): void {
	scaling = value;
}

/**
 * Read the setting once at startup. Never throws: an unreachable server or an older backend
 * without the key leaves upstream's behaviour in place, which is also what an unset value means.
 */
export async function loadUnitScaling(signal?: AbortSignal): Promise<void> {
	try {
		scaling = effectiveUnitScaling(await getJson<SettingResponse>('/setting/unit_scaling', {}, signal));
	} catch {
		/* keep the default */
	}
}
