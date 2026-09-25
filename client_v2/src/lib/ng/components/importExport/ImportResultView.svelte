<script lang="ts">
	/**
	 * Spoolman NG fork addition (#414 step 1): what an import did, or for a dry run would do. It
	 * stays on the page, unlike the classic client's toast, and lists every row error rather
	 * than the first three: a file with forty bad rows is fixed faster from the whole list.
	 */
	import { ng } from '$lib/ng/i18n';
	import { importSucceeded, type ImportResult } from '$lib/ng/importExport';

	let { result, summary }: { result: ImportResult; summary: string } = $props();
	let ok = $derived(importSucceeded(result));
</script>

<div class="result" class:ok class:failed={!ok} role="status">
	{#if ok}
		<p>{summary}</p>
	{:else}
		<p>
			<strong>{ng.settings_import_export_import_errors()}</strong>
			{#if result.dryRun}({ng.settings_import_export_dry_run()}){/if}
		</p>
		<ul class="errors">
			{#each result.errors as err, i (i)}
				<li>{err}</li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	.result {
		margin-top: 10px;
		padding: 8px 10px;
		border-radius: var(--radius-sm);
		border: 1px solid var(--border);
		font-size: 12.5px;
	}
	.result p {
		margin: 0;
	}
	.result.ok {
		border-color: var(--accent-border);
		background: var(--accent-wash);
	}
	.result.failed {
		border-color: var(--danger-soft);
	}
	.errors {
		margin: 6px 0 0;
		padding-left: 18px;
		max-height: 180px;
		overflow-y: auto;
		font-family: var(--font-mono, monospace);
		font-size: 11.5px;
	}
</style>
