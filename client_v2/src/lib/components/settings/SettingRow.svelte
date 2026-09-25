<script lang="ts">
	import type { Snippet } from 'svelte';
	// A titled setting row inside a <Card>: label/description on the left, control
	// on the right (passed as children).
	let { title, desc, children }: { title: string; desc?: string; children: Snippet } = $props();
</script>

<div class="row">
	<div class="row-main">
		<div class="row-title">{title}</div>
		{#if desc}<div class="row-desc">{desc}</div>{/if}
	</div>
	{@render children()}
</div>

<style>
	.row {
		display: flex;
		align-items: center;
		gap: 14px;
		padding: 12px 14px;
	}
	.row-main {
		flex: 1;
		/* Spoolman NG fork addition: a flex item will not shrink below its longest unbreakable
		   word by default, so a description quoting a URL (the AI settings' example endpoints)
		   pushed the control past a phone screen's edge. Let the text column give way and
		   break such a word instead. */
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.row-title {
		font-size: 13px;
	}
	.row-desc {
		font-size: 11.5px;
		color: var(--text-dim);
		margin-top: 2px;
	}
</style>
