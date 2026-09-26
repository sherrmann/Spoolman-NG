<script lang="ts">
	/**
	 * Spoolman NG fork addition (#414 step 2): record a sliced print's filament usage from its
	 * 3MF. Ported from the classic client's `pages/settings/threeMfImport.tsx`; see
	 * docs/design/import-export.md. Administrators only: it writes usage.
	 *
	 * The file is read in the browser (see $lib/ng/threeMfImport). Each filament the print used
	 * becomes a row with a suggested spool, which can be changed or cleared. Apply records each
	 * row's grams through the same `/use` call and Idempotency-Key the weigh-in uses, so retrying
	 * a row whose response was lost cannot count it twice. Unlike the classic client, a partial
	 * failure keeps the failed rows, with their keys, for a retry.
	 */
	import Button from '$components/Button.svelte';
	import Upload from '@lucide/svelte/icons/upload';
	import { ng } from '$lib/ng/i18n';
	import { toasts } from '$lib/stores/toasts.svelte';
	import { inventory } from '$lib/stores/inventory.svelte';
	import { spoolSource } from '$lib/api/spoolSource';
	import { weightAuto } from '$lib/utils/format';
	import { apiErrorMessage } from '$lib/ng/errors';
	import { listAllFilaments, listAllSpools, recordReading } from '$lib/ng/api';
	import { getSpoolName } from '$lib/ng/analytics';
	import { newIdempotencyKey } from '$lib/ng/weighIn';
	import { autoMatchSpoolId, parseThreeMf, ThreeMfError, type ThreeMfFilament } from '$lib/ng/threeMfImport';

	interface Row extends ThreeMfFilament {
		spoolId: number | undefined;
		/**
		 * One per row, kept for the row's life. The server scopes a key to a spool, so it is safe to
		 * keep across a change of spool, and keeping it means going back to a spool whose first
		 * attempt did land (response lost) replays that attempt instead of counting the grams again.
		 */
		attemptKey: string;
	}

	let rows = $state<Row[]>([]);
	let options = $state<{ id: number; label: string }[]>([]);
	let loading = $state(false);
	let applying = $state(false);
	let result = $state<{ text: string; ok: boolean } | null>(null);
	let fileInput = $state<HTMLInputElement>();
	// A file picked while an earlier one is still being read wins; the earlier result is dropped.
	let generation = 0;

	let anySelected = $derived(rows.some((r) => r.spoolId !== undefined));

	function clear() {
		rows = [];
		options = [];
		if (fileInput) fileInput.value = '';
	}

	function errorText(e: unknown): string {
		if (e instanceof ThreeMfError) {
			return e.code === 'no_slice_info'
				? ng.settings_import_export_threemf_no_slice_info()
				: ng.settings_import_export_threemf_invalid_file();
		}
		return apiErrorMessage(e);
	}

	async function picked(e: Event & { currentTarget: HTMLInputElement }) {
		const file = e.currentTarget.files?.[0];
		const mine = ++generation;
		result = null;
		rows = [];
		if (!file) {
			// Some browsers report a cancelled picker as a change with no file; an earlier load
			// that is still running has just been superseded, so its indicator goes too.
			loading = false;
			return;
		}
		loading = true;
		try {
			const [parsed, spools, filaments, vendors] = await Promise.all([
				file.arrayBuffer().then((buf) => parseThreeMf(new Uint8Array(buf))),
				listAllSpools(),
				listAllFilaments(),
				spoolSource.listVendors()
			]);
			if (mine !== generation) return;
			options = spools
				.map((s) => ({
					id: s.id,
					label: [`#${s.id}`, getSpoolName(s, filaments, vendors), s.location].filter(Boolean).join(' · ')
				}))
				.sort((a, b) => a.id - b.id);
			rows = parsed.map((f) => ({
				...f,
				spoolId: autoMatchSpoolId(f, spools, filaments),
				attemptKey: newIdempotencyKey()
			}));
			if (parsed.length === 0) result = { text: ng.settings_import_export_threemf_no_filaments(), ok: false };
		} catch (err) {
			if (mine !== generation) return;
			toasts.error(errorText(err));
			clear();
		} finally {
			if (mine === generation) loading = false;
		}
	}

	function choose(row: Row, value: string) {
		row.spoolId = value === '' ? undefined : Number(value);
		result = null;
	}

	async function apply() {
		if (applying) return;
		applying = true;
		result = null;
		let ok = 0;
		const failed: Row[] = [];
		let firstError: unknown;
		for (const row of rows) {
			if (row.spoolId === undefined) continue;
			try {
				inventory.upsertSpool(await recordReading(row.spoolId, 'weight', row.usedWeight, row.attemptKey));
				ok += 1;
			} catch (err) {
				failed.push(row);
				firstError ??= err;
			}
		}
		applying = false;
		if (failed.length > 0) {
			// Why, so a refused or deleted spool can be told from a dropped connection.
			toasts.error(apiErrorMessage(firstError));
			rows = failed;
			result = {
				text: ng.settings_import_export_threemf_applied_partial({ ok, fail: failed.length }),
				ok: false
			};
		} else {
			clear();
			result = { text: ng.settings_import_export_threemf_applied({ count: ok }), ok: true };
		}
	}
</script>

<section aria-labelledby="ie-threemf">
	<h3 id="ie-threemf">{ng.settings_import_export_threemf_title()}</h3>
	<p class="help">{ng.settings_import_export_threemf_help()}</p>
	<fieldset disabled={applying}>
		<label class="file">
			<Upload size={13} />
			<span>{ng.settings_import_export_threemf_choose_file()}</span>
			<input bind:this={fileInput} type="file" accept=".3mf" onchange={picked} />
		</label>
		{#if rows.length > 0}
			<table>
				<thead>
					<tr>
						<th>{ng.settings_import_export_threemf_col_filament()}</th>
						<th class="num">{ng.settings_import_export_threemf_col_used()}</th>
						<th>{ng.settings_import_export_threemf_col_spool()}</th>
					</tr>
				</thead>
				<tbody>
					{#each rows as row (row.key)}
						<tr>
							<td>
								<span class="fil">
									{#if row.colorHex}<span class="dot" style:background={row.colorHex}></span>{/if}
									{row.type ?? '?'}
								</span>
							</td>
							<td class="num">{weightAuto(row.usedWeight)}</td>
							<td>
								<select
									class="sel"
									value={row.spoolId === undefined ? '' : String(row.spoolId)}
									aria-label={[
										`${ng.settings_import_export_threemf_col_spool()}:`,
										row.type ?? '?',
										row.colorHex,
										weightAuto(row.usedWeight)
									]
										.filter(Boolean)
										.join(' ')}
									onchange={(e) => choose(row, e.currentTarget.value)}
								>
									<option value="">{ng.settings_import_export_threemf_no_match()}</option>
									{#each options as o (o.id)}
										<option value={String(o.id)}>{o.label}</option>
									{/each}
								</select>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
			<div class="actions">
				<Button variant="primary" disabled={!anySelected || applying} onclick={apply}>
					{ng.settings_import_export_threemf_apply()}
				</Button>
			</div>
		{/if}
	</fieldset>
	{#if loading}<p class="help" role="status">{ng.loading()}</p>{/if}
	{#if result}
		<p class="result" class:ok={result.ok} role="status">{result.text}</p>
	{/if}
</section>

<style>
	h3 {
		font-size: 13px;
		font-weight: 600;
		margin: 0 0 4px;
	}
	.help {
		font-size: 12px;
		color: var(--text-muted);
		margin: 0 0 8px;
	}
	fieldset {
		border: none;
		margin: 0;
		padding: 0;
		min-width: 0;
	}
	.file {
		display: inline-flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
		max-width: 100%;
		font-size: 13px;
		color: var(--text-2);
	}
	.file input {
		min-width: 0;
		max-width: 100%;
	}
	table {
		width: 100%;
		margin-top: 10px;
		border-collapse: collapse;
		font-size: 12.5px;
	}
	th {
		text-align: left;
		font-weight: 600;
		color: var(--text-muted);
		padding: 4px 6px;
		border-bottom: 1px solid var(--border);
	}
	td {
		padding: 5px 6px;
		border-bottom: 1px solid var(--border);
		vertical-align: middle;
	}
	.num {
		text-align: right;
		white-space: nowrap;
	}
	.fil {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.dot {
		width: 12px;
		height: 12px;
		border-radius: 50%;
		border: 1px solid var(--border-strong);
		flex: none;
	}
	.sel {
		background: var(--input-bg);
		border: 1px solid var(--border-input);
		border-radius: var(--radius-sm);
		color: var(--text);
		padding: 4px 6px;
		font-size: 12.5px;
		width: 100%;
		max-width: 320px;
		min-width: 0;
	}
	.actions {
		margin-top: 10px;
	}
	.result {
		margin: 10px 0 0;
		font-size: 12.5px;
		color: var(--danger-soft);
	}
	.result.ok {
		color: var(--text);
	}
</style>
