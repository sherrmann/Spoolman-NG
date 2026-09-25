<script lang="ts">
	/**
	 * Spoolman NG fork addition (#412 step 4): what the spools add up to, under the list.
	 *
	 * The selection when there is one, else the spools on screen: the rows loaded under expanded
	 * groups on this page. The group headers' own figures are server totals over whole groups,
	 * which is a different number, so this line never claims to describe more than it shows.
	 * A collapsed pile of identical unused spools renders no rows, so its spools are not in it.
	 */
	import * as m from '$lib/paraglide/messages';
	import { plural } from '$lib/ng/i18n';
	import { librarySelection } from '$lib/ng/librarySelection.svelte';
	import { totals } from '$lib/ng/libraryTotals';
	import { weightAuto } from '$lib/utils/format';
	import { settings } from '$lib/stores/settings.svelte';
	import { inventory } from '$lib/stores/inventory.svelte';
	import type { SpoolVM } from '$lib/utils/library';

	let selecting = $derived(librarySelection.count > 0);
	/**
	 * A selected spool as it stands now, not as it was when ticked. Selected spools on another
	 * page are not re-rendered, so their snapshot goes stale when one is weighed (step 2) or
	 * changed elsewhere; the inventory cache is what live updates keep current.
	 */
	function current(vm: SpoolVM): SpoolVM {
		const spool = inventory.spoolById(vm.spool.id) ?? vm.spool;
		const filament = inventory.filamentById(spool.filamentId) ?? vm.filament;
		return spool === vm.spool && filament === vm.filament ? vm : { ...vm, spool, filament };
	}

	let t = $derived(
		totals(selecting ? [...librarySelection.selected.values()].map(current) : librarySelection.shown())
	);
</script>

{#if t.count > 0}
	<div class="totals" role="status">
		<span class="what">{plural(selecting ? 'spool_totals_selected' : 'spool_totals_shown', t.count)}</span>
		<span>{m['spool.fields.remainingWeight']()} <span class="mono">{weightAuto(t.remaining)}</span></span>
		<span>{m['spool.fields.usedWeight']()} <span class="mono">{weightAuto(t.used)}</span></span>
		{#if t.price !== null}
			<span>{m['spool.fields.price']()} <span class="mono">{settings.formatPrice(t.price)}</span></span>
		{/if}
	</div>
{/if}

<style>
	.totals {
		display: flex;
		flex-wrap: wrap;
		gap: 2px 14px;
		padding: 6px 14px;
		border-top: 1px solid var(--hairline);
		font-size: 11.5px;
		color: var(--text-dim);
	}
	.what {
		color: var(--text-2);
		font-weight: 600;
	}
	.mono {
		color: var(--text-2);
	}
</style>
