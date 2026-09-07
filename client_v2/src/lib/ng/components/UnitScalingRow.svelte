<script lang="ts">
	/**
	 * The `unit_scaling` control (#413), one row inside the General card.
	 *
	 * Shows the EFFECTIVE state rather than the stored one: the setting has never been set on
	 * most instances, and in this client that means "scale" (see $lib/ng/unitScaling for why the
	 * unset case keeps upstream's behaviour). The first flip writes an explicit value, after
	 * which the two agree. Writes are optimistic with a rollback, the way the AI feature flags
	 * are, because a toggle that waits for the server reads as broken.
	 *
	 * Renders nothing for a non-administrator: the write would be refused with a 403, and a
	 * switch that always snaps back is worse than no switch.
	 */
	import Toggle from '$components/Toggle.svelte';
	import SettingRow from '$components/settings/SettingRow.svelte';
	import { ng } from '$lib/ng/i18n';
	import { toasts } from '$lib/stores/toasts.svelte';
	import { getJson } from '$lib/api/http';
	import { setSetting, type SettingResponse } from '$lib/api/settings';
	import { currentUserIsAdmin } from '$lib/ng/me';
	import { effectiveUnitScaling, setUnitScaling } from '$lib/ng/unitScaling.svelte';
	import { apiErrorMessage } from '$lib/ng/errors';

	let show = $state(false);
	let on = $state(true);

	$effect(() => {
		const controller = new AbortController();
		(async () => {
			if (!(await currentUserIsAdmin())) return;
			const setting = await getJson<SettingResponse>('/setting/unit_scaling', {}, controller.signal).catch(
				() => undefined
			);
			on = effectiveUnitScaling(setting);
			show = true;
		})().catch(() => {});
		return () => controller.abort();
	});

	async function flip(value: boolean) {
		on = value;
		setUnitScaling(value);
		try {
			await setSetting('unit_scaling', value);
		} catch (e) {
			on = !value;
			setUnitScaling(!value);
			toasts.error(apiErrorMessage(e));
		}
	}
</script>

{#if show}
	<SettingRow
		title={ng.settings_general_unit_scaling_label()}
		desc={ng.settings_general_unit_scaling_tooltip()}
	>
		<Toggle checked={on} onchange={flip} ariaLabel={ng.settings_general_unit_scaling_label()} />
	</SettingRow>
{/if}
