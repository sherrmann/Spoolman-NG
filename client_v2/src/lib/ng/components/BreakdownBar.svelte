<script lang="ts">
	import { truncTitle } from '$lib/actions/truncated';

	// One row of a ranked horizontal-bar list (Home's "By Material" / "By Manufacturer"
	// tabs). Upstream colored each row by a fixed per-material/per-vendor hex ramp; this
	// port uses rank tiers against the app's own tokens instead; both breakdowns already
	// come sorted largest-first (see $lib/ng/analytics), so "tier" is just the row's
	// position in that order.

	interface Props {
		label: string;
		/** Pre-formatted right-aligned value, e.g. "1.2 kg" or "4 Spools". */
		value: string;
		/** Bar fill, 0-100, relative to the list's largest row. */
		pct: number;
		/** 0 highlights the top row, 1 the next couple, 2 everything else. */
		tier: 0 | 1 | 2;
	}

	let { label, value, pct, tier }: Props = $props();
</script>

<div class="row">
	<div class="head">
		<span class="label" use:truncTitle>{label}</span>
		<span class="value">{value}</span>
	</div>
	<div class="track">
		<div class="fill tier-{tier}" style="width:{Math.max(0, Math.min(100, pct))}%"></div>
	</div>
</div>

<style>
	.row {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 8px;
	}
	.label {
		font-size: 13px;
		font-weight: 600;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.value {
		font-size: 13px;
		font-weight: 700;
		color: var(--text-2);
		flex: none;
	}
	.track {
		height: 7px;
		border-radius: 4px;
		overflow: hidden;
		background: var(--track);
	}
	.fill {
		height: 100%;
		border-radius: 4px;
		transition: width 0.3s ease;
	}
	.tier-0 {
		background: var(--accent);
	}
	.tier-1 {
		background: var(--success);
	}
	.tier-2 {
		background: var(--border-strong);
	}
</style>
