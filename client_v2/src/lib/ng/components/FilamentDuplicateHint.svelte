<script lang="ts">
	/**
	 * A courtesy hint on the new-filament form: "this filament already exists" (an exact match)
	 * or "this looks like X" (from the decision model), modelled on ./DuplicateHint but for
	 * `POST /filament/similar` (spoolman/api/v1/filament.py) instead of `/vendor/similar`.
	 *
	 * Same debounce/abort/request-id pattern as DuplicateHint: every relevant keystroke replaces
	 * the pending timer, and a request superseded by a newer one either never fires or has its
	 * result ignored. Never blocks anything and never reports its own failure -- see
	 * ../similarApi.
	 */
	import { similarFilament, type SimilarFilamentMatch } from '../similarApi';
	import { ng } from '../i18n';

	interface Props {
		/** The manufacturer as currently typed or picked -- name is enough either way, see
		 *  spoolman/duplicates.py's exact-vendor lookup. */
		vendorName: string;
		/** The filament name as currently typed. Checked as-is; trimming and the length floor
		 *  happen here. */
		name: string;
		material: string;
		/** Single-colour hex, without '#'. Leave unset for a multi-colour filament. */
		colorHex?: string;
		/** Comma-separated hexes, without '#'. Leave unset for a single-colour filament. */
		multiColorHexes?: string;
		diameter?: number;
		/** The filament being edited, left out of its own duplicate check. */
		excludeId?: number;
		/** Switch to this existing filament instead of creating a new one. Omit when the caller
		 *  has no clean way to do that -- the hint then renders without a button. */
		onuse?: (filament: SimilarFilamentMatch) => void;
	}
	let { vendorName, name, material, colorHex, multiColorHexes, diameter, excludeId, onuse }: Props = $props();

	/** Below this, the name is still being typed; asking about it wastes a request. Matches
	 *  spoolman/duplicates.py's own floor for the same reason. */
	const MIN_NAME_LENGTH = 2;
	const DEBOUNCE_MS = 500;

	let match = $state<SimilarFilamentMatch | null>(null);
	let isExact = $state(false);
	/** The draft `match` was found for, as a key of its relevant fields -- see {@link draftKey}.
	 *  A result only renders while this still equals the current draft's key, otherwise a slow
	 *  answer for "PLA, black" would keep offering a match for half a second after the colour
	 *  field has already moved on to red, which is no longer a match at all. */
	let matchFor = $state('');

	/** The fields the server actually compares, joined into one string so a change to any of
	 *  them invalidates a result computed for the fields as they stood before. */
	function draftKey(): string {
		return JSON.stringify([
			vendorName.trim().toLowerCase(),
			name.trim().toLowerCase(),
			material.trim().toLowerCase(),
			colorHex ?? '',
			multiColorHexes ?? '',
			diameter ?? '',
			excludeId ?? ''
		]);
	}

	let reqId = 0;
	let controller: AbortController | undefined;
	$effect(() => {
		const draft = {
			vendorName: vendorName.trim() || undefined,
			name: name.trim(),
			material: material.trim(),
			colorHex,
			multiColorHexes,
			diameter
		};
		const exclude = excludeId;
		const key = draftKey();
		// The server's exact tier needs a name -- a material alone never matches
		// (spoolman/duplicates.py's `_exact_filament` bails without one) -- so a name still too
		// short to check is reason enough to skip, whatever else has been filled in.
		if (draft.name.length < MIN_NAME_LENGTH) {
			controller?.abort();
			match = null;
			isExact = false;
			return;
		}
		const mine = ++reqId;
		const timer = setTimeout(() => {
			controller?.abort();
			controller = new AbortController();
			similarFilament(draft, exclude, controller.signal).then((result) => {
				if (mine !== reqId) return;
				matchFor = key;
				if (result.exact) {
					match = result.exact;
					isExact = true;
				} else if (result.suggestion) {
					match = result.suggestion;
					isExact = false;
				} else {
					match = null;
					isExact = false;
				}
			});
			// similarFilament never rejects -- see its own doc comment -- so there is nothing to
			// catch here beyond what it already turns into "no match".
		}, DEBOUNCE_MS);
		return () => clearTimeout(timer);
	});

	let shown = $derived(match && matchFor === draftKey() ? match : null);
</script>

{#if shown}
	<div class="hint" role="status">
		<span class="txt">
			{isExact
				? ng.settings_ai_duplicate_filament_exact({ name: shown.name })
				: ng.settings_ai_duplicate_filament_suggestion({ name: shown.name })}
		</span>
		{#if onuse}
			<button type="button" class="use" onclick={() => onuse(shown)}>
				{ng.settings_ai_duplicate_use({ name: shown.name })}
			</button>
		{/if}
	</div>
{/if}

<style>
	.hint {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 6px 10px;
		margin-top: 4px;
		font-size: 11.5px;
		color: var(--text-muted);
	}
	.txt {
		line-height: 1.4;
	}
	.use {
		flex: none;
		background: none;
		border: none;
		padding: 0;
		font-size: 11.5px;
		font-weight: 600;
		color: var(--accent-link);
		cursor: pointer;
	}
	.use:hover {
		text-decoration: underline;
	}
</style>
