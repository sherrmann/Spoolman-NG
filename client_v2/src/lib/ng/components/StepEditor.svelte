<script lang="ts">
	// The one calibration step editor (#123) -- shared by CalibrationWizard.svelte's content pane
	// and StepEditModal.svelte's standalone form. The React client wrote this same UI twice
	// (CalibrationWizard.tsx and StepResultDrawer.tsx, ~900-1100 lines each): the same flow-rate
	// calculator, the same pressure-advance method toggle and the same VFA speed list, copy-pasted.
	// This is that logic built once. All arithmetic comes from ../calibrationCalc and
	// ../calibrationConfig -- nothing here computes a result itself.
	//
	// Props are intentionally thin: the step type, its current `inputs`/`outputs`, and one
	// `onchange` callback that receives the next value of both. The caller (wizard or modal) owns
	// the actual state and decides when to persist it; this component never calls the API.
	//
	// `variant` is the one addition beyond that: input_shaping's advisory note reads differently
	// depending on where it's shown (calibration_input_shaping_advisory_desc_wizard says "skip this
	// step", ..._desc_drawer says "close this drawer without saving") -- two real message variants
	// for the two real hosts, not a hardcoded string, so the caller says which one it is.
	import { untrack } from 'svelte';
	import { STEP_CONFIGS, AUTO_COMPUTE, type StepField } from '../calibrationConfig';
	import type { CalibrationStepType } from '../calibrationTypes';
	import {
		freshFlowCalc,
		flowCalcResult,
		avoidanceWindow,
		addSpeed,
		type FlowCalcState
	} from '../calibrationCalc';
	import { fieldLabel, optionLabel } from '../calibrationLabels';
	import { ng } from '../i18n';
	import { parseDecimal } from '$lib/utils/numeric';
	import Field from '$components/Field.svelte';
	import FieldGrid from '$components/FieldGrid.svelte';
	import NumberInput from '$components/NumberInput.svelte';
	import SectionLabel from '$components/SectionLabel.svelte';
	import Button from '$components/Button.svelte';
	import * as m from '$lib/paraglide/messages';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import Plus from '@lucide/svelte/icons/plus';
	import Zap from '@lucide/svelte/icons/zap';

	interface StepEditorValue {
		inputs: Record<string, unknown>;
		outputs: Record<string, unknown>;
	}
	interface Props {
		stepType: CalibrationStepType;
		inputs: Record<string, unknown>;
		outputs: Record<string, unknown>;
		onchange: (next: StepEditorValue) => void;
		/** Which advisory copy to show for input_shaping. Defaults to the wizard's. */
		variant?: 'wizard' | 'drawer';
		/**
		 * Record this step as DELIBERATELY skipped, when the host can.
		 *
		 * Distinct from simply moving on: this writes the `_skipped` sentinel, so the step
		 * reads as "Skipped" forever after rather than as not-yet-done. Only offered where
		 * the advisory suggests it -- a printer that handles input shaping itself is a
		 * decision, not a postponement. Omitted by hosts with nowhere to put the result.
		 */
		onmarkskipped?: () => void;
	}
	let { stepType, inputs, outputs, onchange, variant = 'wizard', onmarkskipped }: Props = $props();

	let config = $derived(STEP_CONFIGS[stepType]);

	function toNumber(v: unknown): number | null {
		return typeof v === 'number' && !Number.isNaN(v) ? v : null;
	}

	/** Tower inputs are pa_step_a/measured_height_b; their absence means a hand-typed Pattern value. */
	function hasTowerInputs(vals: Record<string, unknown>): boolean {
		return vals.pa_step_a !== undefined || vals.measured_height_b !== undefined;
	}

	// --- Ephemeral, per-step UI state ---------------------------------------------------
	// None of this is part of `inputs`/`outputs`: it drives the flow-rate calculator, the
	// pressure-advance method toggle and the VFA speed list, and resets whenever the step being
	// edited changes (a different sidebar entry in the wizard, or the type <select> in
	// StepEditModal) -- the same per-stepType reset the React client did with a `[stepType]`
	// effect. `untrack` on the read of `inputs` keeps this effect from re-running (and clobbering
	// the user's own choice of PA method) on every keystroke; it should only re-derive when the
	// step identity itself changes.
	let paMethod = $state<'tower' | 'pattern'>('tower');
	let flowCalc = $state<FlowCalcState>(freshFlowCalc());
	let artifactSpeeds = $state<number[]>([]);
	let newSpeedDraft = $state('');

	$effect(() => {
		const st = stepType;
		untrack(() => {
			paMethod = st === 'pressure_advance' && !hasTowerInputs(inputs) ? 'pattern' : 'tower';
			flowCalc = freshFlowCalc();
			artifactSpeeds = [];
			newSpeedDraft = '';
		});
	});

	function setInputField(key: string, value: unknown) {
		const next = { ...inputs };
		if (value === undefined) delete next[key];
		else next[key] = value;
		onchange({ inputs: next, outputs: autoCompute(next, outputs) });
	}
	function setOutputField(key: string, value: unknown) {
		const next = { ...outputs };
		if (value === undefined) delete next[key];
		else next[key] = value;
		onchange({ inputs, outputs: next });
	}
	function mergeOutputs(patch: Record<string, unknown>) {
		onchange({ inputs, outputs: { ...outputs, ...patch } });
	}

	/** AUTO_COMPUTE[stepType], recomputed from `nextInputs` and merged over `currentOutputs`. */
	function autoCompute(
		nextInputs: Record<string, unknown>,
		currentOutputs: Record<string, unknown>
	): Record<string, unknown> {
		const fn = AUTO_COMPUTE[stepType];
		if (!fn || (stepType === 'pressure_advance' && paMethod === 'pattern')) return currentOutputs;
		const asNumbers: Record<string, number | null> = {};
		for (const f of config.inputFields) asNumbers[f.key] = toNumber(nextInputs[f.key]);
		const computed = fn(asNumbers);
		return Object.keys(computed).length > 0 ? { ...currentOutputs, ...computed } : currentOutputs;
	}

	function choosePaMethod(method: 'tower' | 'pattern') {
		paMethod = method;
		// A tower measurement and a hand-typed Pattern value must never blend into one number --
		// switching method clears the result (matching the React client) and, switching TO
		// Pattern, also clears the now-hidden tower inputs rather than leaving them saved but
		// invisible (an improvement over the React client, which leaves them in the form's
		// untouched "inputs" namespace even once its own Test Setup section stops rendering them).
		onchange({ inputs: method === 'pattern' ? {} : inputs, outputs: {} });
	}

	// --- Flow rate calculator -----------------------------------------------------------
	let flowResult = $derived(flowCalcResult(flowCalc));

	function chooseFlowMethod(method: FlowCalcState['method']) {
		flowCalc = freshFlowCalc(method);
	}
	function applyFlowCalc() {
		if (flowResult === null) return;
		setOutputField('flow_ratio', flowResult);
		flowCalc = freshFlowCalc(flowCalc.method);
	}

	// --- VFA artifact speeds --------------------------------------------------------------
	function addArtifactSpeed() {
		const parsed = parseDecimal(newSpeedDraft);
		const next = addSpeed(artifactSpeeds, parsed ?? null);
		if (next === artifactSpeeds) return; // blank/unparseable entry -- addSpeed ignored it
		artifactSpeeds = next;
		newSpeedDraft = '';
		const window = avoidanceWindow(artifactSpeeds);
		if (window) mergeOutputs(window);
	}
	function removeArtifactSpeed(idx: number) {
		artifactSpeeds = artifactSpeeds.filter((_, i) => i !== idx);
		// An empty list must leave outputs alone (see avoidanceWindow's own doc comment) --
		// removing the last entry does NOT zero out a previously computed/typed window.
		const window = avoidanceWindow(artifactSpeeds);
		if (window) mergeOutputs(window);
	}

	let showInputs = $derived(
		config.inputFields.length > 0 && !(stepType === 'pressure_advance' && paMethod === 'pattern')
	);
	let showAutoBadge = $derived(
		(!!AUTO_COMPUTE[stepType] && !(stepType === 'pressure_advance' && paMethod === 'pattern')) ||
			stepType === 'vfa'
	);
</script>

{#snippet fieldRow(field: StepField, value: unknown, onset: (v: unknown) => void)}
	<Field label={fieldLabel(config, field)}>
		{#if field.type === 'select'}
			<select
				class="sel"
				value={typeof value === 'string' ? value : ''}
				aria-label={fieldLabel(config, field)}
				onchange={(e) => onset(e.currentTarget.value || undefined)}
			>
				<option value="">—</option>
				{#each field.options ?? [] as opt (opt)}
					<option value={opt}>{optionLabel(opt)}</option>
				{/each}
			</select>
		{:else}
			<NumberInput
				value={typeof value === 'number' ? value : ''}
				min={field.min}
				max={field.max}
				step={field.step ?? (field.precision != null ? 1 / 10 ** field.precision : 1)}
				unit={field.unit}
				ariaLabel={fieldLabel(config, field)}
				onchange={(v) => onset(v)}
				onclear={() => onset(undefined)}
			/>
		{/if}
	</Field>
{/snippet}

<div class="editor">
	{#if stepType === 'pressure_advance'}
		<section class="block">
			<SectionLabel>{ng.calibration_sections_test_method()}</SectionLabel>
			<div class="method-row">
				<div class="toggle-group" role="radiogroup" aria-label={ng.calibration_sections_test_method()}>
					<button
						type="button"
						class="toggle"
						class:active={paMethod === 'tower'}
						aria-pressed={paMethod === 'tower'}
						onclick={() => choosePaMethod('tower')}>{ng.calibration_pa_method_tower()}</button
					>
					<button
						type="button"
						class="toggle"
						class:active={paMethod === 'pattern'}
						aria-pressed={paMethod === 'pattern'}
						onclick={() => choosePaMethod('pattern')}>{ng.calibration_pa_method_pattern()}</button
					>
				</div>
				<p class="hint">
					{paMethod === 'tower' ? ng.calibration_pa_tower_desc() : ng.calibration_pa_pattern_desc()}
				</p>
			</div>
		</section>
	{/if}

	{#if stepType === 'flow_rate'}
		<section class="block flow-calc">
			<SectionLabel>{ng.calibration_flow_calc_title()}</SectionLabel>
			<div class="toggle-group" role="radiogroup" aria-label={ng.calibration_flow_calc_title()}>
				<button
					type="button"
					class="toggle"
					class:active={flowCalc.method === 'yolo'}
					aria-pressed={flowCalc.method === 'yolo'}
					onclick={() => chooseFlowMethod('yolo')}>{ng.calibration_flow_calc_method_yolo()}</button
				>
				<button
					type="button"
					class="toggle"
					class:active={flowCalc.method === 'legacy'}
					aria-pressed={flowCalc.method === 'legacy'}
					onclick={() => chooseFlowMethod('legacy')}>{ng.calibration_flow_calc_method_legacy()}</button
				>
			</div>
			<p class="hint">
				{flowCalc.method === 'yolo'
					? ng.calibration_flow_calc_yolo_desc()
					: ng.calibration_flow_calc_legacy_desc()}
			</p>

			{#if flowCalc.method === 'yolo'}
				<p class="hint">{ng.calibration_flow_calc_yolo_pass1_desc()}</p>
				<FieldGrid labelWidth="180px">
					<Field label={ng.calibration_flow_calc_current_flow_ratio()}>
						<NumberInput
							value={flowCalc.yoloOld ?? ''}
							min={0.1}
							max={2}
							step={0.001}
							onchange={(v) => (flowCalc = { ...flowCalc, yoloOld: v })}
							onclear={() => (flowCalc = { ...flowCalc, yoloOld: null })}
						/>
					</Field>
					<Field label={ng.calibration_flow_calc_modifier()}>
						<NumberInput
							value={flowCalc.yoloModifier ?? ''}
							min={-1}
							max={1}
							step={0.001}
							onchange={(v) => (flowCalc = { ...flowCalc, yoloModifier: v })}
							onclear={() => (flowCalc = { ...flowCalc, yoloModifier: null })}
						/>
					</Field>
				</FieldGrid>
			{:else}
				<p class="hint">{ng.calibration_flow_calc_legacy_pass1_desc()}</p>
				<span class="pass-label">{ng.calibration_flow_calc_pass1()}</span>
				<FieldGrid labelWidth="180px">
					<Field label={ng.calibration_flow_calc_flow_ratio()}>
						<NumberInput
							value={flowCalc.pass1Ratio ?? ''}
							min={0.1}
							max={2}
							step={0.00001}
							onchange={(v) => (flowCalc = { ...flowCalc, pass1Ratio: v })}
							onclear={() => (flowCalc = { ...flowCalc, pass1Ratio: null })}
						/>
					</Field>
					<Field label={ng.calibration_flow_calc_modifier()}>
						<NumberInput
							value={flowCalc.pass1Modifier ?? ''}
							min={-50}
							max={50}
							step={0.1}
							unit="%"
							onchange={(v) => (flowCalc = { ...flowCalc, pass1Modifier: v })}
							onclear={() => (flowCalc = { ...flowCalc, pass1Modifier: null })}
						/>
					</Field>
				</FieldGrid>
				<span class="pass-label"
					>{ng.calibration_flow_calc_pass2()}
					<span class="optional">({ng.calibration_optional()})</span></span
				>
				<p class="hint">{ng.calibration_flow_calc_pass2_desc()}</p>
				<FieldGrid labelWidth="180px">
					<Field label={ng.calibration_flow_calc_flow_ratio()}>
						<NumberInput
							value={flowCalc.pass2Ratio ?? ''}
							min={0.1}
							max={2}
							step={0.00001}
							onchange={(v) => (flowCalc = { ...flowCalc, pass2Ratio: v })}
							onclear={() => (flowCalc = { ...flowCalc, pass2Ratio: null })}
						/>
					</Field>
					<Field label={ng.calibration_flow_calc_modifier()}>
						<NumberInput
							value={flowCalc.pass2Modifier ?? ''}
							min={-50}
							max={50}
							step={0.1}
							unit="%"
							onchange={(v) => (flowCalc = { ...flowCalc, pass2Modifier: v })}
							onclear={() => (flowCalc = { ...flowCalc, pass2Modifier: null })}
						/>
					</Field>
				</FieldGrid>
			{/if}

			<div class="flow-result">
				<span class="result-label">
					{flowCalc.method === 'yolo'
						? ng.calibration_flow_calc_new_flow_ratio()
						: ng.calibration_flow_calc_result()}
				</span>
				<span class="result-value">{flowResult ?? '—'}</span>
				<Button variant="primary" disabled={flowResult === null} onclick={applyFlowCalc}>
					{ng.calibration_flow_calc_apply()}
				</Button>
			</div>
		</section>
	{/if}

	{#if stepType === 'input_shaping'}
		<div class="advisory">
			<Zap size={16} />
			<div class="advisory-body">
				<strong>{ng.calibration_input_shaping_advisory_title()}</strong>
				<p>
					{variant === 'wizard'
						? ng.calibration_input_shaping_advisory_desc_wizard()
						: ng.calibration_input_shaping_advisory_desc_drawer()}
				</p>
				{#if onmarkskipped}
					<button type="button" class="advisory-skip" onclick={onmarkskipped}>
						{ng.calibration_input_shaping_advisory_skip()}
					</button>
				{/if}
			</div>
		</div>
	{/if}

	{#if showInputs}
		<section class="block">
			<SectionLabel>{ng.calibration_sections_test_setup()}</SectionLabel>
			<FieldGrid labelWidth="190px">
				{#each config.inputFields as field (field.key)}
					{@render fieldRow(field, inputs[field.key], (v) => setInputField(field.key, v))}
				{/each}
			</FieldGrid>
		</section>
	{/if}

	{#if stepType === 'vfa'}
		<section class="block">
			<SectionLabel>{ng.calibration_vfa_artifact_speeds()}</SectionLabel>
			<p class="hint">{ng.calibration_vfa_artifact_speeds_desc()}</p>
			{#if artifactSpeeds.length > 0}
				<ul class="speed-list">
					{#each artifactSpeeds as speed, idx (idx + '-' + speed)}
						<li class="speed-row">
							<span>{speed} mm/s</span>
							<button
								type="button"
								class="icon-btn"
								aria-label={m['buttons.delete']()}
								onclick={() => removeArtifactSpeed(idx)}
							>
								<Trash2 size={14} />
							</button>
						</li>
					{/each}
				</ul>
			{/if}
			<div class="speed-add">
				<NumberInput
					bind:value={newSpeedDraft}
					min={0}
					unit="mm/s"
					placeholder={ng.calibration_vfa_speed_placeholder()}
					ariaLabel={ng.calibration_vfa_speed_placeholder()}
				/>
				<Button variant="outline" onclick={addArtifactSpeed} disabled={parseDecimal(newSpeedDraft) == null}>
					<Plus size={14} />
					{ng.calibration_vfa_add_speed()}
				</Button>
			</div>
		</section>
	{/if}

	<section class="block result-card">
		{#if showAutoBadge}
			<SectionLabel>
				{ng.calibration_sections_your_result()}
				{#snippet right()}<span class="auto-badge">{ng.calibration_sections_auto_computed()}</span>{/snippet}
			</SectionLabel>
		{:else}
			<SectionLabel>{ng.calibration_sections_your_result()}</SectionLabel>
		{/if}
		<FieldGrid labelWidth="190px">
			{#each config.outputFields as field (field.key)}
				{@render fieldRow(field, outputs[field.key], (v) => setOutputField(field.key, v))}
			{/each}
		</FieldGrid>
	</section>
</div>

<style>
	.editor {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.block {
		margin-bottom: 6px;
	}
	.hint {
		margin: 0 0 12px;
		font-size: 12.5px;
		line-height: 1.5;
		color: var(--text-dim);
	}
	.method-row {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-start;
		gap: 14px;
	}
	.method-row .hint {
		flex: 1;
		min-width: 200px;
		margin-bottom: 0;
	}

	.toggle-group {
		display: inline-flex;
		padding: 2px;
		border-radius: var(--radius);
		background: var(--surface-raised);
		border: 1px solid var(--border);
		flex: none;
	}
	.toggle {
		border: none;
		background: none;
		padding: 6px 12px;
		border-radius: calc(var(--radius) - 2px);
		font-size: 12.5px;
		font-weight: 600;
		color: var(--text-dim);
		cursor: pointer;
	}
	.toggle.active {
		background: var(--accent-fill);
		color: #fff;
	}

	.sel {
		background: var(--input-bg);
		border: 1px solid var(--border-input);
		border-radius: var(--radius-sm);
		color: var(--text);
		padding: 8px 8px;
		font-size: 13px;
		width: 100%;
	}

	.flow-calc {
		border: 1px solid var(--border);
		border-radius: var(--radius-lg);
		padding: 14px 16px;
		background: var(--surface);
	}
	.pass-label {
		display: block;
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-faint);
		margin-bottom: 8px;
	}
	.pass-label .optional {
		text-transform: none;
		font-weight: 400;
		letter-spacing: 0;
	}
	.flow-result {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-top: 10px;
		padding-top: 12px;
		border-top: 1px solid var(--border-soft);
	}
	.result-label {
		font-size: 12px;
		color: var(--text-dim);
	}
	.result-value {
		flex: 1;
		font-weight: 700;
		font-size: 15px;
		font-family: var(--font-mono, monospace);
	}

	.advisory {
		display: flex;
		gap: 10px;
		padding: 12px 14px;
		border-radius: var(--radius-lg);
		background: var(--accent-wash-soft);
		border: 1px solid var(--accent-wash);
		color: var(--accent-soft);
		margin-bottom: 6px;
	}
	.advisory-body strong {
		display: block;
		font-size: 13px;
		color: var(--text);
		margin-bottom: 4px;
	}
	.advisory-skip {
		align-self: flex-start;
		margin-top: 8px;
		background: none;
		border: none;
		padding: 0;
		font: inherit;
		font-size: 12.5px;
		font-weight: 600;
		color: var(--accent-soft);
		cursor: pointer;
	}
	.advisory-skip:hover {
		text-decoration: underline;
	}
	.advisory-body p {
		margin: 0;
		font-size: 12.5px;
		line-height: 1.5;
		color: var(--text-dim);
	}

	.speed-list {
		list-style: none;
		margin: 0 0 10px;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.speed-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 6px 10px;
		border-radius: var(--radius);
		background: var(--surface-raised);
		border: 1px solid var(--border);
		font-size: 13px;
	}
	.icon-btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 4px;
		border: none;
		border-radius: var(--radius);
		background: none;
		color: var(--text-faint);
		cursor: pointer;
	}
	.icon-btn:hover {
		color: var(--danger);
		background: var(--danger-wash);
	}
	.speed-add {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.result-card {
		background: var(--accent-wash-soft);
		border: 1px solid var(--accent-wash);
		border-radius: var(--radius-lg);
		padding: 14px 16px 4px;
	}
	.auto-badge {
		font-style: italic;
		font-weight: 400;
		opacity: 0.8;
	}
</style>
