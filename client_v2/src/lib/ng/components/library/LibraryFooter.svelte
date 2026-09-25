<script lang="ts">
	/**
	 * Spoolman NG fork seam (#412): what sits under the Library list.
	 *
	 * FilamentList imports this in place of upstream's Pagination (Tier 2), which gives the fork
	 * an in-flow footer for the bulk bar without touching the list's template or positioning
	 * anything over it. Every prop is forwarded, so upstream can change Pagination's freely.
	 */
	import type { ComponentProps } from 'svelte';
	import Pagination from '$components/Pagination.svelte';
	import BulkBar from './BulkBar.svelte';

	let props: ComponentProps<typeof Pagination> = $props();
</script>

<BulkBar />
<Pagination {...props} />
