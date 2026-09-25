<script lang="ts">
	/**
	 * Spoolman NG fork addition (#414 step 1): export, import and the printable inventory report,
	 * one section of the settings page. Ported from the classic client's
	 * `pages/settings/importExportSettings.tsx`; see docs/design/import-export.md.
	 *
	 * Unlike the fork's other panels this one shows to everyone: a read-only user may export and
	 * print, since both only read. The import form renders for administrators only, as the server
	 * refuses a read-only user's POST.
	 */
	import Button from '$components/Button.svelte';
	import NgSettingsSection from '$lib/ng/components/NgSettingsSection.svelte';
	import Download from '@lucide/svelte/icons/download';
	import Printer from '@lucide/svelte/icons/printer';
	import { ng } from '$lib/ng/i18n';
	import { toasts } from '$lib/stores/toasts.svelte';
	import { settings } from '$lib/stores/settings.svelte';
	import { weightAuto } from '$lib/utils/format';
	import { currentUserIsAdmin } from '$lib/ng/me';
	import { apiErrorMessage } from '$lib/ng/errors';
	import { listAllFilaments, listAllSpools } from '$lib/ng/api';
	import {
		EXPORT_ENTITIES,
		IMPORT_MODES,
		downloadExport,
		formatFromFilename,
		importData,
		importEntityFor,
		importSucceeded,
		inventoryReport,
		type DataFormat,
		type ExportEntity,
		type ImportMode,
		type ImportResult
	} from '$lib/ng/importExport';
	import { printReport } from '$lib/ng/reportPrint';
	import ImportResultView from './ImportResultView.svelte';

	let admin = $state(false);
	$effect(() => {
		currentUserIsAdmin()
			.then((a) => (admin = a))
			.catch(() => {});
	});

	const entityLabel: Record<ExportEntity, () => string> = {
		spools: ng.settings_import_export_entities_spools,
		filaments: ng.settings_import_export_entities_filaments,
		vendors: ng.settings_import_export_entities_vendors
	};
	const modeLabel: Record<ImportMode, () => string> = {
		create: ng.settings_import_export_modes_create,
		upsert: ng.settings_import_export_modes_upsert,
		skip_existing: ng.settings_import_export_modes_skip_existing
	};

	// --- export ------------------------------------------------------------------
	let exporting = $state<string | null>(null);
	async function exportAs(entity: ExportEntity, fmt: DataFormat) {
		exporting = `${entity}.${fmt}`;
		try {
			await downloadExport(entity, fmt);
		} catch (e) {
			toasts.error(apiErrorMessage(e));
		} finally {
			exporting = null;
		}
	}

	// --- import ------------------------------------------------------------------
	let entity = $state<ExportEntity>('spools');
	let mode = $state<ImportMode>('create');
	// On by default: a first pass that only validates is the safe habit, since a real import of
	// the wrong file is not undone by anything short of a backup.
	let dryRun = $state(true);
	let fmt = $state<DataFormat>('csv');
	let file = $state<File | null>(null);
	let importing = $state(false);
	let result = $state<ImportResult | null>(null);
	let fileInput = $state<HTMLInputElement>();

	/** A result describes the form as it was run; once the form changes it no longer applies. */
	function forget() {
		result = null;
	}

	function picked(e: Event & { currentTarget: HTMLInputElement }) {
		file = e.currentTarget.files?.[0] ?? null;
		result = null;
		if (file) fmt = formatFromFilename(file.name) ?? fmt;
	}

	async function runImport(e: SubmitEvent) {
		e.preventDefault();
		if (!file) {
			toasts.error(ng.settings_import_export_no_file());
			return;
		}
		importing = true;
		result = null;
		try {
			result = await importData(importEntityFor(entity), fmt, mode, dryRun, await file.text());
			if (importSucceeded(result) && !result.dryRun) {
				toasts.success(summary(result));
				// Done with this file: left selected, a second click would import it again, and in
				// "create" mode, which ignores ids, that inserts every row a second time.
				file = null;
				if (fileInput) fileInput.value = '';
			}
		} catch (err) {
			toasts.error(apiErrorMessage(err));
		} finally {
			importing = false;
		}
	}

	function summary(r: ImportResult): string {
		const counts = ng.settings_import_export_result({
			created: r.created,
			updated: r.updated,
			skipped: r.skipped
		});
		return r.dryRun ? `${ng.settings_import_export_dry_run_prefix()} ${counts}` : counts;
	}

	// --- report ------------------------------------------------------------------
	let reporting = $state(false);
	async function report() {
		reporting = true;
		try {
			const [spools, filaments] = await Promise.all([listAllSpools(), listAllFilaments()]);
			printReport(inventoryReport(spools, filaments), {
				heading: ng.settings_import_export_report_heading(),
				spools: ng.settings_import_export_entities_spools(),
				remaining: ng.home_total_weight(),
				value: ng.home_total_value(),
				material: ng.spool_fields_material(),
				count: ng.filament_fields_spool_count(),
				weight: ng.home_total_weight(),
				formatWeight: (g) => weightAuto(g),
				formatValue: (v) => settings.formatPrice(v)
			});
		} catch (e) {
			toasts.error(apiErrorMessage(e));
		} finally {
			reporting = false;
		}
	}
</script>

<NgSettingsSection title={ng.settings_import_export_tab()}>
	<div class="body">
		<section aria-labelledby="ie-export">
			<h3 id="ie-export">{ng.settings_import_export_export_title()}</h3>
			<p class="help">{ng.settings_import_export_export_help()}</p>
			<ul class="exports">
				{#each EXPORT_ENTITIES as e (e)}
					<li>
						<span class="name">{entityLabel[e]()}</span>
						{#each ['csv', 'json'] as const as f (f)}
							<Button
								variant="outline"
								disabled={exporting !== null}
								ariaLabel={`${entityLabel[e]()} · ${f.toUpperCase()}`}
								onclick={() => exportAs(e, f)}><Download size={13} /> {f.toUpperCase()}</Button
							>
						{/each}
					</li>
				{/each}
			</ul>
		</section>

		{#if admin}
			<section aria-labelledby="ie-import">
				<h3 id="ie-import">{ng.settings_import_export_import_title()}</h3>
				<p class="help">{ng.settings_import_export_import_help()}</p>
				<!-- The whole form is locked while a request is out: a result, or the clearing of the
				     file after a real import, belongs to the form as it was submitted, and changing it
				     mid-request would pin that result on a different file or discard a newer one. -->
				<form class="import" onsubmit={runImport}>
					<fieldset disabled={importing}>
						<select
							class="sel"
							bind:value={entity}
							onchange={forget}
							aria-label={ng.settings_import_export_entity_label()}
						>
							{#each EXPORT_ENTITIES as e (e)}
								<option value={e}>{entityLabel[e]()}</option>
							{/each}
						</select>
						<select
							class="sel"
							bind:value={mode}
							onchange={forget}
							aria-label={ng.settings_import_export_mode_label()}
						>
							{#each IMPORT_MODES as m (m)}
								<option value={m}>{modeLabel[m]()}</option>
							{/each}
						</select>
						<select
							class="sel"
							bind:value={fmt}
							onchange={forget}
							aria-label={ng.settings_import_export_format_label()}
						>
							<option value="csv">CSV</option>
							<option value="json">JSON</option>
						</select>
						<label class="file">
							<span>{ng.settings_import_export_choose_file()}</span>
							<input
								bind:this={fileInput}
								type="file"
								accept=".csv,.json,text/csv,application/json"
								onchange={picked}
							/>
						</label>
						<label class="chk"
							><input type="checkbox" bind:checked={dryRun} onchange={forget} />
							{ng.settings_import_export_dry_run()}</label
						>
						<Button type="submit" variant={dryRun ? 'outline' : 'primary'} disabled={importing || !file}>
							{dryRun ? ng.settings_import_export_validate() : ng.settings_import_export_import_button()}
						</Button>
					</fieldset>
				</form>
				{#if result}
					<ImportResultView {result} summary={summary(result)} />
				{/if}
			</section>
		{/if}

		<section aria-labelledby="ie-report">
			<h3 id="ie-report">{ng.settings_import_export_report_title()}</h3>
			<p class="help">{ng.settings_import_export_report_help()}</p>
			<Button variant="outline" disabled={reporting} onclick={report}
				><Printer size={13} /> {ng.settings_import_export_print_report()}</Button
			>
		</section>
	</div>
</NgSettingsSection>

<style>
	.body {
		padding: 12px 14px;
		display: flex;
		flex-direction: column;
		gap: 18px;
	}
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
	.exports {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.exports li {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 13px;
	}
	.name {
		min-width: 120px;
	}
	fieldset {
		display: contents;
	}
	.import {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		font-size: 13px;
	}
	.sel {
		background: var(--input-bg);
		border: 1px solid var(--border-input);
		border-radius: var(--radius-sm);
		color: var(--text);
		padding: 5px 8px;
		font-size: 13px;
	}
	.file {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.file span {
		color: var(--text-2);
	}
	.chk {
		display: inline-flex;
		align-items: center;
		gap: 5px;
	}
	.chk input {
		accent-color: var(--accent);
	}
</style>
