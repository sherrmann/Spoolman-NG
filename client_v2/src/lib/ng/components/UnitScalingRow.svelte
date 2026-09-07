<script lang="ts">
	/**
	 * The `unit_scaling` control (#413), one row inside the General card.
	 *
	 * The switch IS the flag every weight on screen reads (see $lib/ng/unitScaling.svelte),
	 * which +layout loads at startup; there is no second fetch and no copy to fall out of step
	 * with the list. It therefore shows the EFFECTIVE state: on most instances the setting has
	 * never been set, which in this client means "scale". The first flip writes an explicit
	 * value, after which the stored and the shown state agree. Writes are optimistic with a
	 * rollback, the way the AI feature flags are, because a toggle that waits for the server
	 * reads as broken.
	 *
	 * Renders nothing for a non-administrator: the write would be refused with a 403, and a
	 * switch that always snaps back is worse than no switch.
	 */
	import Toggle from '$components/Toggle.svelte';
	import SettingRow from '$components/settings/SettingRow.svelte';
	import { ng } from '$lib/ng/i18n';
	import { toasts } from '$lib/stores/toasts.svelte';
	import { setSetting } from '$lib/api/settings';
	import { currentUserIsAdmin } from '$lib/ng/me';
	import { isUnitScaling, setUnitScaling } from '$lib/ng/unitScaling.svelte';
	import { apiErrorMessage } from '$lib/ng/errors';

	let show = $state(false);
	let on = $derived(isUnitScaling());

	$effect(() => {
		currentUserIsAdmin()
			.then((admin) => (show = admin))
			.catch(() => {});
	});

	async function flip(value: boolean) {
		setUnitScaling(value);
		try {
			await setSetting('unit_scaling', value);
		} catch (e) {
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
