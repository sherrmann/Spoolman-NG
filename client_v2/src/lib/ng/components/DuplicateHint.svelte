<script lang="ts">
	/**
	 * A courtesy hint next to a manufacturer-name field: "a vendor named X already exists" or
	 * "this looks like X" (from the decision model), each with a button that switches the form
	 * to the existing vendor instead of creating a near-duplicate one.
	 *
	 * Debounced and abortable, same pattern as $lib/components/library/SearchBox.svelte: every
	 * keystroke replaces the pending timer, and a request superseded by a newer one either never
	 * fires or has its result ignored, so a slow answer for "Bambu" can never land after a
	 * faster one for "Bambu Lab" has already replaced it on screen. Never blocks anything and
	 * never reports its own failure -- see ../similarApi.
	 */
	import { similarVendor, type SimilarVendorMatch } from '../similarApi';
	import { ng } from '../i18n';

	interface Props {
		/** The name as currently typed. Checked as-is; trimming and the length floor happen here. */
		name: string;
		/** The vendor being renamed, left out of its own duplicate check. */
		excludeId?: number;
		/** Switch the form to this existing vendor instead of creating a new one. */
		onuse: (vendor: SimilarVendorMatch) => void;
	}
	let { name, excludeId, onuse }: Props = $props();

	/** Below this, the name is still being typed; asking about it wastes a request. */
	const MIN_LENGTH = 2;
	const DEBOUNCE_MS = 500;

	let match = $state<SimilarVendorMatch | null>(null);
	let isExact = $state(false);

	let reqId = 0;
	let controller: AbortController | undefined;
	$effect(() => {
		const typed = name.trim();
		const exclude = excludeId;
		if (typed.length < MIN_LENGTH) {
			controller?.abort();
			match = null;
			isExact = false;
			return;
		}
		const mine = ++reqId;
		const timer = setTimeout(() => {
			controller?.abort();
			controller = new AbortController();
			similarVendor(typed, exclude, controller.signal).then((result) => {
				if (mine !== reqId) return;
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
			// similarVendor never rejects -- see its own doc comment -- so there is nothing to
			// catch here beyond what it already turns into "no match".
		}, DEBOUNCE_MS);
		return () => clearTimeout(timer);
	});
</script>

{#if match}
	<div class="hint" role="status">
		<span class="txt">
			{isExact
				? ng.settings_ai_duplicate_exact({ name: match.name })
				: ng.settings_ai_duplicate_suggestion({ name: match.name })}
		</span>
		<button type="button" class="use" onclick={() => onuse(match!)}>
			{ng.settings_ai_duplicate_use({ name: match.name })}
		</button>
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
