<script lang="ts">
	/**
	 * Spoolman NG fork seam (#412): what sits under the Library list.
	 *
	 * FilamentList imports this in place of upstream's Pagination (Tier 2), which gives the fork
	 * an in-flow footer for the bulk bar and the totals line (step 4) without touching the list's template or positioning
	 * anything over it. Every prop is forwarded, so upstream can change Pagination's freely.
	 */
	import type { ComponentProps } from 'svelte';
	import Pagination from '$components/Pagination.svelte';
	import BulkBar from './BulkBar.svelte';
	import LibraryTotals from './LibraryTotals.svelte';

	let props: ComponentProps<typeof Pagination> = $props();
</script>

<!-- display: contents -- the wrapper only scopes the phone rules below to the Library's pager;
     the three parts stay direct flex children of the list column, as they were. -->
<div class="library-footer">
	<BulkBar />
	<LibraryTotals />
	<Pagination {...props} />
</div>

<style>
	.library-footer {
		display: contents;
	}

	/* On a small phone the "1-20 of 52 groups" text, the page numbers and the 44px page-size
	   picker do not fit on one line, so the pager took two rows -- with the totals line above
	   it, about 190px of a 568px screen. When there are page numbers, the text goes: they show
	   where you are, and the totals line directly above already counts the spools. The numbers
	   and the picker then share one row (a long run of page numbers can still wrap rather than
	   overflow). With a single page there are no numbers, so the text stays. */
	@media (max-width: 560px) {
		.library-footer :global(.pager:has(.nums) .count) {
			display: none;
		}
		.library-footer :global(.pager) {
			padding: 4px 12px;
		}
	}
</style>
