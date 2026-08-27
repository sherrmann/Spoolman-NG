<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve --
	   selectFilament() below always builds a bare `?filament=...` query string, which resolves
	   against the CURRENT url -- the same base-path-independent convention as
	   $lib/settings/params.ts's gotoEntity(). Resolving it again here would double-apply the
	   deploy base path. */
	// Calibration route (#123): `?filament=<id>` picks which filament's calibration history this
	// page shows; with none given, a picker stands in for the whole page until one is chosen (and
	// choosing one rewrites the URL, so the result is linkable). Sessions for that filament list
	// newest first, each expandable to its own step history.
	//
	// The three floors of calibration UI live in their own files, shared where the brief calls
	// for it: CalibrationWizard.svelte (the guided 9-step flow), StepEditModal.svelte (add/edit one
	// step outside the wizard) and SessionFormModal.svelte (session metadata). Both step editors
	// share StepEditor.svelte's flow-rate/PA/VFA UI rather than each carrying their own copy.
	//
	// Data loading/live-refresh follows routes/orders/+page.svelte's own pattern (an
	// AbortController-guarded load, a refresh() that aborts and re-issues, a retry button on
	// error) -- except the "resource" here (which filament's sessions) can itself change, via the
	// picker or a `?filament=` link, so `sessionsLoaded` resets to show a loading state again on a
	// genuine filament change, not just on first load.
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { SvelteSet } from 'svelte/reactivity';
	import { isAbortError, HttpError } from '$lib/api/http';
	import { listAllFilaments } from '$lib/ng/api';
	import { spoolSource } from '$lib/api/spoolSource';
	import {
		listSessions,
		createSession,
		deleteSession as apiDeleteSession,
		deleteStep as apiDeleteStep
	} from '$lib/ng/calibrationApi';
	import { isSkipped, type CalibrationSession, type CalibrationStepResult } from '$lib/ng/calibrationTypes';
	import type { CalibrationStepType } from '$lib/ng/calibrationTypes';
	import {
		STEP_CONFIGS,
		WIZARD_STEP_ORDER,
		type StepConfig,
		type StepField
	} from '$lib/ng/calibrationConfig';
	import {
		fieldLabel,
		optionLabel,
		stepTypeLabel,
		statusLabel,
		confidenceLabel
	} from '$lib/ng/calibrationLabels';
	import { ng } from '$lib/ng/i18n';
	import { getFilamentName } from '$lib/ng/analytics';
	import { dateLocale } from '$lib/utils/datetime';
	import { toasts } from '$lib/stores/toasts.svelte';
	import * as m from '$lib/paraglide/messages';
	import type { ForkFilament } from '$lib/ng/types';
	import type { Vendor } from '$lib/types';
	import Button from '$components/Button.svelte';
	import ConfirmDialog from '$components/ConfirmDialog.svelte';
	import CalibrationWizard from '$lib/ng/components/CalibrationWizard.svelte';
	import StepEditModal from '$lib/ng/components/StepEditModal.svelte';
	import SessionFormModal from '$lib/ng/components/SessionFormModal.svelte';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import Plus from '@lucide/svelte/icons/plus';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';

	// --- ?filament= ------------------------------------------------------------------------

	let filamentId = $derived(page.url.searchParams.get('filament') ?? undefined);

	function selectFilament(id: string) {
		if (!id) return;
		void goto(`?filament=${id}`, { keepFocus: true, noScroll: true });
	}

	// --- filament list (for the picker, and to resolve the chosen filament's name) ---------

	let filaments = $state<ForkFilament[]>([]);
	let vendors = $state<Vendor[]>([]);

	async function loadFilaments(signal: AbortSignal) {
		try {
			const [f, v] = await Promise.all([listAllFilaments(signal), spoolSource.listVendors(signal)]);
			filaments = f;
			vendors = v;
		} catch (e) {
			if (isAbortError(e, signal)) return;
			console.error('Failed to load filaments', e);
		}
	}
	$effect(() => {
		const c = new AbortController();
		loadFilaments(c.signal);
		return () => c.abort();
	});

	let filamentOptions = $derived(
		[...filaments]
			.map((f) => ({ id: f.id, label: getFilamentName(f, vendors) }))
			.sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: 'base' }))
	);
	let selectedFilament = $derived(filaments.find((f) => f.id === filamentId));

	// --- sessions for the selected filament --------------------------------------------------

	let sessions = $state<CalibrationSession[]>([]);
	let sessionsLoaded = $state(false);
	let sessionsError = $state(false);
	let sessionsController = new AbortController();

	async function loadSessions(id: string, signal: AbortSignal) {
		try {
			const raw = await listSessions(id, signal);
			// Newest first: the backend's own ordering isn't part of its contract, so this page
			// sorts explicitly rather than assuming.
			sessions = raw
				.slice()
				.sort((a, b) => new Date(b.registered).getTime() - new Date(a.registered).getTime());
			sessionsError = false;
		} catch (e) {
			if (isAbortError(e, signal)) return;
			console.error('Failed to load calibration sessions', e);
			sessionsError = true;
		} finally {
			sessionsLoaded = true;
		}
	}

	function refreshSessions() {
		sessionsController.abort();
		sessionsController = new AbortController();
		if (filamentId) loadSessions(filamentId, sessionsController.signal);
	}

	$effect(() => {
		const id = filamentId; // dependency: a genuine filament change reloads from scratch
		sessionsLoaded = false;
		sessions = [];
		if (id) refreshSessions();
		else sessionsLoaded = true;
		return () => sessionsController.abort();
	});

	function reportError(e: unknown, context: string) {
		console.error(context, e);
		toasts.error(m['notifications.error']({ statusCode: e instanceof HttpError ? e.status : '?' }));
	}

	// --- start/resume wizard -----------------------------------------------------------------

	let inProgressSessions = $derived(sessions.filter((s) => s.status === 'in_progress'));
	let resumeChoice = $state<number | undefined>(undefined);
	$effect(() => {
		if (inProgressSessions.length === 0) {
			resumeChoice = undefined;
		} else if (resumeChoice == null || !inProgressSessions.some((s) => s.id === resumeChoice)) {
			resumeChoice = inProgressSessions[0].id;
		}
	});

	let wizardSession = $state<CalibrationSession | undefined>();
	let startingWizard = $state(false);

	async function startWizard() {
		if (!filamentId || startingWizard) return;
		startingWizard = true;
		try {
			const created = await createSession(filamentId, { status: 'in_progress' });
			sessions = [created, ...sessions];
			wizardSession = created;
		} catch (e) {
			reportError(e, 'Failed to start calibration session');
		} finally {
			startingWizard = false;
		}
	}

	function resumeWizard(id: number | undefined) {
		const found = sessions.find((s) => s.id === id);
		if (found) wizardSession = found;
	}

	// --- session/step dialogs ------------------------------------------------------------------

	let editingSession = $state<CalibrationSession | undefined>();
	let deletingSession = $state<CalibrationSession | undefined>();
	let deletingSessionBusy = $state(false);

	let addingStepFor = $state<CalibrationSession | undefined>();
	let editingStep = $state<{ sessionId: number; step: CalibrationStepResult } | undefined>();
	let deletingStep = $state<CalibrationStepResult | undefined>();
	let deletingStepBusy = $state(false);

	async function confirmDeleteSession() {
		if (!deletingSession) return;
		deletingSessionBusy = true;
		try {
			await apiDeleteSession(deletingSession.id);
			deletingSession = undefined;
			refreshSessions();
		} catch (e) {
			reportError(e, 'Failed to delete calibration session');
		} finally {
			deletingSessionBusy = false;
		}
	}

	async function confirmDeleteStep() {
		if (!deletingStep) return;
		deletingStepBusy = true;
		try {
			await apiDeleteStep(deletingStep.id);
			deletingStep = undefined;
			refreshSessions();
		} catch (e) {
			reportError(e, 'Failed to delete calibration step');
		} finally {
			deletingStepBusy = false;
		}
	}

	// --- expand/collapse a session's step history -----------------------------------------------

	// SvelteSet, not a plain Set: toggled in place below, and SvelteSet is what makes that
	// mutation trigger the row's own reactivity.
	let expandedIds = new SvelteSet<number>();
	function toggleExpand(id: number) {
		if (expandedIds.has(id)) expandedIds.delete(id);
		else expandedIds.add(id);
	}

	function formatDate(iso: string | undefined): string | undefined {
		if (!iso) return undefined;
		const d = new Date(iso);
		if (Number.isNaN(d.getTime())) return undefined;
		return new Intl.DateTimeFormat(dateLocale(), { month: 'short', day: 'numeric', year: 'numeric' }).format(
			d
		);
	}

	function formatValue(field: StepField, value: unknown): string {
		if (field.type === 'select' && typeof value === 'string') return optionLabel(value);
		const unit = field.unit ? ` ${field.unit}` : '';
		return `${value}${unit}`;
	}
	function fieldOf(cfg: StepConfig, key: string): StepField | undefined {
		return [...cfg.inputFields, ...cfg.outputFields].find((f) => f.key === key);
	}

	// --- "recommended settings" summary: the latest selected_values per step type, across every
	// session for this filament (oldest session first, so a later one wins). --------------------
	let recommended = $derived.by(() => {
		const latest: Partial<Record<CalibrationStepType, CalibrationStepResult>> = {};
		for (const session of [...sessions].reverse()) {
			for (const step of session.steps) {
				if (step.selectedValues && Object.keys(step.selectedValues).length > 0) {
					latest[step.stepType] = step;
				}
			}
		}
		return WIZARD_STEP_ORDER.filter((t) => latest[t]).map((t) => ({ stepType: t, step: latest[t]! }));
	});
</script>

<svelte:head>
	<title>{ng.calibration_title()} | Spoolman</title>
</svelte:head>

<div class="page scroll-y">
	<div class="header">
		<h1>{ng.calibration_title()}</h1>
		{#if filamentId}
			<div class="header-actions">
				{#if inProgressSessions.length === 0}
					<Button onclick={startWizard} disabled={startingWizard}>{ng.calibration_wizard_start()}</Button>
				{:else if inProgressSessions.length === 1}
					<Button onclick={() => resumeWizard(inProgressSessions[0].id)}
						>{ng.calibration_wizard_resume()}</Button
					>
				{:else}
					<select class="sel" bind:value={resumeChoice} aria-label={ng.calibration_wizard_resume()}>
						{#each inProgressSessions as s (s.id)}
							<option value={s.id}>{formatDate(s.startedAt ?? s.registered) ?? `#${s.id}`}</option>
						{/each}
					</select>
					<Button onclick={() => resumeWizard(resumeChoice)}>{ng.calibration_wizard_resume()}</Button>
				{/if}
			</div>
		{/if}
	</div>

	{#if !filamentId}
		<div class="picker">
			<label class="picker-label" for="calibration-filament-picker">{ng.orders_select_filament()}</label>
			<select
				id="calibration-filament-picker"
				class="sel picker-select"
				value=""
				onchange={(e) => selectFilament(e.currentTarget.value)}
			>
				<option value="" disabled>{ng.orders_select_filament()}</option>
				{#each filamentOptions as opt (opt.id)}
					<option value={opt.id}>{opt.label}</option>
				{/each}
			</select>
		</div>
	{:else}
		<div class="filament-bar">
			<span class="filament-name">
				{selectedFilament ? getFilamentName(selectedFilament, vendors) : `#${filamentId}`}
			</span>
			<!-- No fork message key fits "pick a different filament" -- hardcoded English, listed in
			     this task's report. -->
			<a class="change-link" href={resolve('/calibration')}>Change filament</a>
		</div>

		{#if recommended.length > 0}
			<section class="recommended-card">
				<h2>{ng.calibration_recommended_title()}</h2>
				<div class="recommended-grid">
					{#each recommended as { stepType, step } (stepType)}
						{@const cfg = STEP_CONFIGS[stepType]}
						<div class="rec-tile">
							<span class="rec-type">{stepTypeLabel(stepType)}</span>
							<div class="rec-values">
								{#each cfg.recommendedKeys as key (key)}
									{#if step.selectedValues?.[key] !== undefined && step.selectedValues?.[key] !== null}
										{@const field = fieldOf(cfg, key)}
										<div class="rec-row">
											<span class="rec-key">{field ? fieldLabel(cfg, field) : key}</span>
											<span class="rec-val">
												{field
													? formatValue(field, step.selectedValues[key])
													: String(step.selectedValues[key])}
											</span>
										</div>
									{/if}
								{/each}
							</div>
						</div>
					{/each}
				</div>
			</section>
		{:else if sessionsLoaded && !sessionsError}
			<p class="empty small">{ng.calibration_no_recommended()}</p>
		{/if}

		<h2 class="history-title">{ng.calibration_fields_history()}</h2>

		{#if !sessionsLoaded}
			<div class="state">{ng.loading()}</div>
		{:else if sessionsError}
			<div class="state error">
				<button class="retry" onclick={refreshSessions}>{ng.buttons_refresh()}</button>
			</div>
		{:else if sessions.length === 0}
			<p class="empty">{ng.calibration_no_data()}</p>
		{:else}
			<ul class="list">
				{#each sessions as session (session.id)}
					{@const expanded = expandedIds.has(session.id)}
					<li class="row" class:expanded>
						<!-- Stretched hit target via a <button> (not <a>): expanding a session's history
						     isn't a navigation, matching routes/orders/+page.svelte's own `.order-link`
						     (also a button, also opening something in place rather than going anywhere).
						     `.row` is the positioned ancestor; `.row-right`'s controls are raised above the
						     stretched ::after with z-index, same as every other list page in this fork. -->
						<button class="row-link" onclick={() => toggleExpand(session.id)} aria-expanded={expanded}>
							<ChevronRight class="chevron" size={15} />
							<span class="status-pill status-{session.status}">{statusLabel(session.status)}</span>
							<span class="row-meta">
								{#if session.printerName}<span>{session.printerName}</span>
									<span class="dot" aria-hidden="true">·</span>{/if}
								{#if session.nozzleDiameter != null}<span>{session.nozzleDiameter} mm</span>
									<span class="dot" aria-hidden="true">·</span>{/if}
								<span class="dates">
									{formatDate(session.startedAt ?? session.registered) ?? '—'}
									{#if session.completedAt}– {formatDate(session.completedAt)}{/if}
								</span>
							</span>
						</button>
						<span class="row-right">
							<span class="steps-count">
								{ng.calibration_fields_steps_count({ count: session.steps.length })} / {WIZARD_STEP_ORDER.length}
							</span>
							<button
								type="button"
								class="icon-btn"
								onclick={() => (editingSession = session)}
								title={ng.calibration_buttons_edit_session()}
								aria-label={ng.calibration_buttons_edit_session()}><Pencil size={14} /></button
							>
							<button
								type="button"
								class="icon-btn danger"
								onclick={() => (deletingSession = session)}
								title={ng.calibration_buttons_delete_session()}
								aria-label={ng.calibration_buttons_delete_session()}><Trash2 size={14} /></button
							>
						</span>

						{#if expanded}
							<div class="step-history">
								<div class="step-history-head">
									<span>{ng.calibration_fields_history()}</span>
									<Button variant="outline" onclick={() => (addingStepFor = session)}>
										<Plus size={13} />
										{ng.calibration_buttons_add_step()}
									</Button>
								</div>
								{#if session.steps.length === 0}
									<p class="empty-inline">{ng.calibration_fields_no_steps()}</p>
								{:else}
									<ul class="step-list">
										{#each session.steps as step (step.id)}
											{@const cfg = STEP_CONFIGS[step.stepType]}
											{@const skipped = isSkipped(step)}
											{@const hasRecommended =
												!skipped && step.selectedValues && Object.keys(step.selectedValues).length > 0}
											<li class="step-row">
												<div class="step-main">
													<span class="step-type">{stepTypeLabel(step.stepType)}</span>
													{#if skipped}
														<span class="tag skip">{ng.calibration_step_status_skipped()}</span>
													{:else if hasRecommended}
														<span class="tag done">{ng.calibration_step_status_done()}</span>
													{:else}
														<span class="tag incomplete">{ng.calibration_step_status_incomplete()}</span>
													{/if}
													{#if step.confidence}
														<span class="confidence">
															{ng.calibration_confidence_display({ level: confidenceLabel(step.confidence) })}
														</span>
													{/if}
													<span class="step-actions">
														<button
															type="button"
															class="icon-btn"
															onclick={() => (editingStep = { sessionId: session.id, step })}
															title={ng.calibration_buttons_edit_step()}
															aria-label={ng.calibration_buttons_edit_step()}><Pencil size={13} /></button
														>
														<button
															type="button"
															class="icon-btn danger"
															onclick={() => (deletingStep = step)}
															title={ng.calibration_buttons_delete_step()}
															aria-label={ng.calibration_buttons_delete_step()}><Trash2 size={13} /></button
														>
													</span>
												</div>
												{#if hasRecommended}
													<div class="step-values">
														{#each cfg.recommendedKeys as key (key)}
															{#if step.selectedValues?.[key] !== undefined && step.selectedValues?.[key] !== null}
																{@const field = fieldOf(cfg, key)}
																<span class="value-chip">
																	<span class="value-key">{field ? fieldLabel(cfg, field) : key}</span>
																	<span class="value-val">
																		{field
																			? formatValue(field, step.selectedValues[key])
																			: String(step.selectedValues[key])}
																	</span>
																</span>
															{/if}
														{/each}
													</div>
												{/if}
												{#if step.notes}
													<p class="step-notes">{step.notes}</p>
												{/if}
											</li>
										{/each}
									</ul>
								{/if}
							</div>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
	{/if}
</div>

{#if wizardSession}
	<CalibrationWizard
		session={wizardSession}
		onsuccess={refreshSessions}
		onclose={() => (wizardSession = undefined)}
	/>
{/if}

{#if editingSession}
	<SessionFormModal
		mode="edit"
		session={editingSession}
		onclose={() => (editingSession = undefined)}
		onsuccess={refreshSessions}
	/>
{/if}

{#if addingStepFor}
	<StepEditModal
		sessionId={addingStepFor.id}
		onclose={() => (addingStepFor = undefined)}
		onsuccess={refreshSessions}
	/>
{/if}

{#if editingStep}
	<StepEditModal
		sessionId={editingStep.sessionId}
		step={editingStep.step}
		onclose={() => (editingStep = undefined)}
		onsuccess={refreshSessions}
	/>
{/if}

<ConfirmDialog
	open={!!deletingSession}
	busy={deletingSessionBusy}
	title={deletingSession ? statusLabel(deletingSession.status) : ''}
	lines={[ng.calibration_delete_session_confirm()]}
	confirmLabel={m['buttons.delete']()}
	onconfirm={confirmDeleteSession}
	onclose={() => (deletingSession = undefined)}
/>

<ConfirmDialog
	open={!!deletingStep}
	busy={deletingStepBusy}
	title={deletingStep ? stepTypeLabel(deletingStep.stepType) : ''}
	lines={[ng.calibration_delete_step_confirm()]}
	confirmLabel={m['buttons.delete']()}
	onconfirm={confirmDeleteStep}
	onclose={() => (deletingStep = undefined)}
/>

<style>
	.page {
		max-width: 1100px;
		width: 100%;
		margin: 0 auto;
		padding: 20px 22px 40px;
		display: flex;
		flex-direction: column;
		gap: 20px;
	}

	.header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		flex-wrap: wrap;
	}
	.header h1 {
		margin: 0;
		font-size: 20px;
		font-weight: 800;
		letter-spacing: -0.02em;
	}
	.header-actions {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.sel {
		background: var(--input-bg);
		border: 1px solid var(--border-input);
		border-radius: var(--radius-sm);
		color: var(--text);
		padding: 8px 8px;
		font-size: 13px;
	}

	.picker {
		display: flex;
		flex-direction: column;
		gap: 8px;
		max-width: 420px;
		margin: 40px auto;
		text-align: center;
	}
	.picker-label {
		font-size: 13px;
		color: var(--text-dim);
	}
	.picker-select {
		width: 100%;
	}

	.filament-bar {
		display: flex;
		align-items: baseline;
		gap: 10px;
	}
	.filament-name {
		font-size: 15px;
		font-weight: 700;
	}
	.change-link {
		font-size: 12px;
		color: var(--text-faint);
	}
	.change-link:hover {
		color: var(--accent-soft);
	}

	.recommended-card {
		background: color-mix(in srgb, var(--success) 8%, var(--surface));
		border: 1px solid color-mix(in srgb, var(--success) 25%, var(--border));
		border-radius: var(--radius-lg);
		padding: 14px 16px;
	}
	.recommended-card h2 {
		margin: 0 0 10px;
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.07em;
		color: var(--success);
	}
	.recommended-grid {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
	}
	.rec-tile {
		flex: 1 1 160px;
		max-width: 240px;
		padding: 10px 12px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-left: 3px solid var(--success);
		border-radius: var(--radius);
	}
	.rec-type {
		display: block;
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-faint);
		margin-bottom: 6px;
	}
	.rec-values {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.rec-row {
		display: flex;
		justify-content: space-between;
		gap: 8px;
		font-size: 12.5px;
	}
	.rec-key {
		color: var(--text-faint);
	}
	.rec-val {
		font-weight: 700;
	}

	.history-title {
		margin: 4px 0 0;
		font-size: 13px;
		font-weight: 700;
		color: var(--text-2);
	}

	.state {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 48px 0;
		color: var(--text-faint);
		font-size: 13px;
	}
	.retry {
		background: var(--accent-fill);
		color: #fff;
		border: none;
		border-radius: var(--radius);
		padding: 8px 16px;
		font-size: 13px;
		font-weight: 600;
		cursor: pointer;
	}
	.retry:hover {
		background: var(--accent-fill-hover);
	}

	.empty {
		text-align: center;
		padding: 32px 0;
		color: var(--text-faint);
		font-size: 13px;
	}
	.empty.small {
		padding: 6px 0 0;
		text-align: left;
	}

	.list {
		/* Semantic list, not a bulleted one -- display:flex does NOT suppress an <li>'s ::marker
		   in Chromium (see routes/orders/+page.svelte's own comment on this). */
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.row {
		position: relative;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 12px;
		padding: 12px 14px;
		border-radius: var(--radius-lg);
		background: var(--surface);
		border: 1px solid var(--border);
	}
	.row:hover {
		background: var(--surface-raised);
	}

	/* `.row-link` must NOT be position:relative -- its ::after stretches over the whole `.row`
	   (the positioned ancestor), and giving this its own position would confine that ::after to
	   the button's own box, the bug already fixed once on routes/orders and routes/locations. */
	.row-link {
		display: flex;
		align-items: center;
		gap: 10px;
		flex: 1 1 auto;
		min-width: 0;
		background: none;
		border: none;
		padding: 0;
		font: inherit;
		color: var(--text);
		cursor: pointer;
		text-align: left;
	}
	.row-link::after {
		content: '';
		position: absolute;
		inset: 0;
		border-radius: inherit;
	}
	.row-link:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	.row-link :global(.chevron) {
		flex: none;
		color: var(--text-faint);
		transition: transform 0.15s;
	}
	.row.expanded .row-link :global(.chevron) {
		transform: rotate(90deg);
	}

	.status-pill {
		flex: none;
		font-size: 11px;
		font-weight: 700;
		white-space: nowrap;
		padding: 3px 10px;
		border-radius: 999px;
		background: var(--surface-raised);
		color: var(--text-dim);
	}
	.status-pill.status-in_progress {
		background: var(--accent-wash);
		color: var(--accent-soft);
	}
	.status-pill.status-complete {
		background: color-mix(in srgb, var(--success) 15%, transparent);
		color: var(--success);
	}

	.row-meta {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 12px;
		color: var(--text-faint);
		min-width: 0;
		flex-wrap: wrap;
	}
	.dot {
		flex: none;
	}
	.dates {
		white-space: nowrap;
	}

	/* Raised above `.row-link`'s stretched ::after, same as every other list page here. */
	.row-right {
		position: relative;
		z-index: 1;
		display: flex;
		align-items: center;
		gap: 6px;
		flex: none;
	}
	.steps-count {
		font-size: 11.5px;
		color: var(--text-faint);
		white-space: nowrap;
		margin-right: 4px;
	}

	.icon-btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 5px;
		border: none;
		border-radius: var(--radius);
		background: none;
		color: var(--text-faint);
		cursor: pointer;
	}
	.icon-btn:hover {
		color: var(--text);
		background: var(--surface-raised);
	}
	.icon-btn.danger:hover {
		color: var(--danger);
		background: var(--danger-wash);
	}

	.step-history {
		position: relative;
		z-index: 1;
		flex-basis: 100%;
		margin-top: 6px;
		padding-top: 12px;
		border-top: 1px solid var(--border-soft);
	}
	.step-history-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 10px;
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-faint);
	}
	.empty-inline {
		margin: 0;
		font-size: 12.5px;
		color: var(--text-faint);
	}

	.step-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.step-row {
		padding: 8px 10px;
		border-radius: var(--radius);
		background: var(--surface-raised);
		border: 1px solid var(--border-soft);
	}
	.step-main {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}
	.step-type {
		font-size: 12.5px;
		font-weight: 700;
	}
	.tag {
		font-size: 10.5px;
		font-weight: 700;
		padding: 2px 7px;
		border-radius: 999px;
		background: var(--surface);
		color: var(--text-faint);
		border: 1px solid var(--border);
	}
	.tag.done {
		background: color-mix(in srgb, var(--success) 15%, transparent);
		color: var(--success);
		border-color: transparent;
	}
	.tag.skip {
		background: var(--surface);
		color: var(--text-dim);
	}
	.tag.incomplete {
		background: var(--danger-wash);
		color: var(--danger-soft, var(--danger));
		border-color: transparent;
	}
	.confidence {
		font-size: 11px;
		color: var(--text-faint);
	}
	.step-actions {
		margin-left: auto;
		display: flex;
		gap: 2px;
	}
	.step-values {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin-top: 8px;
	}
	.value-chip {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 3px 8px;
		border-radius: var(--radius);
		background: var(--surface);
		border: 1px solid var(--border);
		font-size: 11.5px;
	}
	.value-key {
		color: var(--text-faint);
	}
	.value-val {
		font-weight: 700;
	}
	.step-notes {
		margin: 8px 0 0;
		font-size: 12px;
		line-height: 1.5;
		color: var(--text-dim);
	}

	@media (max-width: 700px) {
		.row-right {
			margin-left: auto;
		}
	}
</style>
