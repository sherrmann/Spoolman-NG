<script lang="ts">
	/**
	 * The operator's AI configuration: endpoint, models, keys, and which features are on.
	 *
	 * Renders NOTHING for a non-administrator. The React client shows this panel to everyone and
	 * lets the server sort it out, which reads badly: /ai/status strips the provider fields for
	 * a non-admin, so a read-only user sees a blank form indistinguishable from an unconfigured
	 * server, fills it in, and discovers on Save that they were never allowed. Asking who is
	 * looking first costs one request and removes that whole path.
	 *
	 * The API keys are write-only. The server returns whether one is stored, never the value, so
	 * the field starts empty every time and an empty field on Save means "leave it alone" rather
	 * than "clear it" -- clearing is its own button, because those two intentions look identical
	 * in a blank text box and only one of them is recoverable.
	 */
	import Button from '$components/Button.svelte';
	import Card from '$components/Card.svelte';
	import Toggle from '$components/Toggle.svelte';
	import SettingRow from '$components/settings/SettingRow.svelte';
	import Check from '@lucide/svelte/icons/check';
	import Minus from '@lucide/svelte/icons/minus';
	import XIcon from '@lucide/svelte/icons/x';
	import { ng } from '$lib/ng/i18n';
	import { toasts } from '$lib/stores/toasts.svelte';
	import { getSettings, setSetting, parseSetting, type SettingsMap } from '$lib/api/settings';
	import {
		isAdmin,
		aiAdminStatus,
		aiProbe,
		setAiKeys,
		ollamaModels,
		pullOllamaModel,
		type AiAdminStatus,
		type AiCapabilities,
		type TriState
	} from '$lib/ng/aiApi';
	import { AI_PRESETS, OLLAMA_SUGGESTIONS } from '$lib/ng/aiPresets';
	import { FEATURES, blockedReason, toggleDisabled, type FeatureKey } from '$lib/ng/aiFeatures';

	let admin = $state(false);
	let loaded = $state(false);
	let status = $state<AiAdminStatus | null>(null);

	// The form. Seeded from the server once loaded; the two key fields never are.
	let baseUrl = $state('');
	let model = $state('');
	let visionModel = $state('');
	let apiKey = $state('');
	let sttBaseUrl = $state('');
	let sttModel = $state('');
	let sttApiKey = $state('');

	let saving = $state(false);
	let probing = $state(false);
	/** A probe run here beats the server's cached one: it describes the form in front of you. */
	let probed = $state<AiCapabilities | null>(null);
	let flags = $state<Record<string, boolean>>({});
	let installed = $state<string[]>([]);
	let pulling = $state<string | null>(null);
	let pullPercent = $state<number | null>(null);

	let capabilities = $derived(probed ?? status?.capabilities ?? null);
	let locked = $derived(new Set(status?.envLocked ?? []));
	let ready = $derived({
		configured: status?.configured ?? false,
		sttConfigured: status?.sttConfigured ?? false,
		vision: (capabilities?.vision ?? 'unknown') as TriState
	});
	let urlsValid = $derived(
		(!baseUrl || /^https?:\/\/.+/.test(baseUrl)) && (!sttBaseUrl || /^https?:\/\/.+/.test(sttBaseUrl))
	);

	$effect(() => {
		const controller = new AbortController();
		(async () => {
			admin = await isAdmin(controller.signal);
			if (!admin) {
				loaded = true;
				return;
			}
			const [s, settingsMap] = await Promise.all([
				aiAdminStatus(controller.signal),
				getSettings(controller.signal).catch(() => ({}) as SettingsMap)
			]);
			status = s;
			baseUrl = s.baseUrl;
			model = s.model;
			visionModel = s.visionModel;
			sttBaseUrl = s.sttBaseUrl;
			sttModel = s.sttModel;
			flags = Object.fromEntries(FEATURES.map((f) => [f.key, parseSetting(settingsMap[f.key], false)]));
			flags.ai_voice_autosend = parseSetting(settingsMap.ai_voice_autosend, false);
			loaded = true;
			if (s.capabilities?.isOllama) installed = (await ollamaModels(controller.signal)).installed;
		})().catch(() => (loaded = true));
		return () => controller.abort();
	});

	async function refreshStatus() {
		status = await aiAdminStatus();
	}

	async function save() {
		if (saving || !urlsValid) return;
		saving = true;
		try {
			// The four provider fields are ordinary settings; the keys are not, and go through
			// /ai/config so they are never round-tripped back to any client.
			await Promise.all([
				locked.has('base_url') ? null : setSetting('ai_base_url', baseUrl),
				locked.has('model') ? null : setSetting('ai_model', model),
				locked.has('vision_model') ? null : setSetting('ai_vision_model', visionModel),
				locked.has('stt_base_url') ? null : setSetting('ai_stt_base_url', sttBaseUrl),
				locked.has('stt_model') ? null : setSetting('ai_stt_model', sttModel)
			]);
			// Only sent when something was typed. An empty box means "keep the stored key".
			if (apiKey || sttApiKey) {
				await setAiKeys({
					apiKey: apiKey || undefined,
					sttApiKey: sttApiKey || undefined
				});
				apiKey = '';
				sttApiKey = '';
			}
			await refreshStatus();
			toasts.success(ng.buttons_save());
		} catch {
			toasts.error(ng.settings_ai_probe_failed());
		} finally {
			saving = false;
		}
	}

	async function clearKey(which: 'chat' | 'stt') {
		try {
			await setAiKeys(which === 'chat' ? { apiKey: null } : { sttApiKey: null });
			await refreshStatus();
		} catch {
			toasts.error(ng.settings_ai_probe_failed());
		}
	}

	async function probe() {
		if (probing) return;
		probing = true;
		try {
			// Sent with what is on screen, not what is stored, so a new endpoint can be tested
			// without first saving over a working one.
			probed = await aiProbe({
				baseUrl: locked.has('base_url') ? undefined : baseUrl,
				apiKey: apiKey || undefined,
				model: locked.has('model') ? undefined : model,
				visionModel: locked.has('vision_model') ? undefined : visionModel
			});
			if (probed.isOllama) installed = (await ollamaModels()).installed;
		} catch {
			probed = {
				ok: false,
				error: ng.settings_ai_probe_failed(),
				models: [],
				chat: 'unknown',
				tools: 'unknown',
				vision: 'unknown',
				isOllama: false
			};
		} finally {
			probing = false;
		}
	}

	async function setFlag(key: string, value: boolean) {
		flags = { ...flags, [key]: value };
		try {
			await setSetting(key, value);
		} catch {
			flags = { ...flags, [key]: !value };
			toasts.error(ng.settings_ai_probe_failed());
		}
	}

	async function pull(name: string) {
		if (pulling) return;
		pulling = name;
		pullPercent = null;
		try {
			for await (const p of pullOllamaModel(name)) {
				pullPercent = p.percent ?? null;
			}
			installed = (await ollamaModels()).installed;
			toasts.success(ng.settings_ai_models_pulled({ model: name }));
		} catch {
			toasts.error(ng.settings_ai_probe_failed());
		} finally {
			pulling = null;
			pullPercent = null;
		}
	}

	const FEATURE_LABEL: Record<FeatureKey, () => string> = {
		ai_feature_chat: ng.settings_ai_features_chat,
		ai_feature_voice: ng.settings_ai_features_voice,
		ai_feature_nl_search: ng.settings_ai_features_nl_search,
		ai_feature_scan_to_spool: ng.settings_ai_features_scan_to_spool,
		ai_feature_mcp: ng.settings_ai_features_mcp
	};

	function reasonText(key: FeatureKey): string | undefined {
		const def = FEATURES.find((f) => f.key === key)!;
		const reason = blockedReason(def, ready);
		if (reason === 'requires_config') return ng.settings_ai_features_requires_config();
		if (reason === 'requires_stt') return ng.settings_ai_features_requires_stt();
		if (reason === 'requires_vision') return ng.settings_ai_features_requires_vision();
		// Not a blocker, just the truth about this client: the setting is server-wide and the
		// React client does implement these.
		return def.absentHere ? ng.settings_ai_features_absent_here() : undefined;
	}

	const TRI_LABEL: Record<TriState, () => string> = {
		yes: ng.settings_ai_probe_yes,
		no: ng.settings_ai_probe_no,
		unknown: ng.settings_ai_probe_unknown
	};
</script>

<!-- Nothing is rendered until we know who is asking, so the panel never flashes into view for
     a user who may not use it. -->
{#if loaded && admin}
	<!-- A named region, because this panel's "Base URL" is not the only one on the page: the
	     General section has one too, and without a region they are indistinguishable to anyone
	     navigating by label. -->
	<section aria-label={ng.settings_ai_tab()}>
		<div class="sec-label">{ng.settings_ai_tab()}</div>
		<p class="intro">{ng.settings_ai_description()}</p>

		<Card divided>
			<SettingRow title={ng.settings_ai_preset_label()}>
				<select
					class="ctl"
					aria-label={ng.settings_ai_preset_label()}
					disabled={locked.has('base_url')}
					onchange={(e) => {
						const p = AI_PRESETS.find((x) => x.key === e.currentTarget.value);
						if (p) baseUrl = p.baseUrl;
					}}
				>
					<option value="">{ng.settings_ai_preset_placeholder()}</option>
					{#each AI_PRESETS as p (p.key)}
						<option value={p.key}>{p.label}</option>
					{/each}
				</select>
			</SettingRow>

			<SettingRow
				title={ng.settings_ai_base_url_label()}
				desc={locked.has('base_url') ? ng.settings_ai_env_locked() : ng.settings_ai_base_url_tooltip()}
			>
				<input
					class="ctl"
					aria-label={ng.settings_ai_base_url_label()}
					bind:value={baseUrl}
					disabled={locked.has('base_url')}
					placeholder="http://localhost:11434/v1"
					aria-invalid={!!baseUrl && !/^https?:\/\/.+/.test(baseUrl)}
				/>
			</SettingRow>

			<SettingRow
				title={ng.settings_ai_api_key_label()}
				desc={locked.has('api_key') ? ng.settings_ai_env_locked() : ng.settings_ai_api_key_tooltip()}
			>
				<div class="stack">
					<input
						class="ctl"
						type="password"
						autocomplete="off"
						aria-label={ng.settings_ai_api_key_label()}
						bind:value={apiKey}
						disabled={locked.has('api_key')}
						placeholder={status?.apiKeySet
							? ng.settings_ai_api_key_placeholder_set()
							: ng.settings_ai_api_key_placeholder_unset()}
					/>
					{#if status?.apiKeySet && !locked.has('api_key')}
						<button class="link" onclick={() => clearKey('chat')}>
							{ng.settings_ai_api_key_clear()}
						</button>
					{/if}
				</div>
			</SettingRow>

			<SettingRow title={ng.settings_ai_model_label()} desc={ng.settings_ai_model_tooltip()}>
				<input
					class="ctl"
					aria-label={ng.settings_ai_model_label()}
					bind:value={model}
					disabled={locked.has('model')}
					list="ai-models"
				/>
			</SettingRow>

			<SettingRow title={ng.settings_ai_vision_model_label()} desc={ng.settings_ai_vision_model_tooltip()}>
				<input
					class="ctl"
					aria-label={ng.settings_ai_vision_model_label()}
					bind:value={visionModel}
					disabled={locked.has('vision_model')}
					list="ai-models"
				/>
			</SettingRow>
		</Card>

		<!-- Populated by the probe, so the model fields suggest what the endpoint actually serves
	     rather than what someone remembered. -->
		<datalist id="ai-models">
			{#each capabilities?.models ?? [] as name (name)}<option value={name}></option>{/each}
		</datalist>

		<div class="sec-label">{ng.settings_ai_stt_title()}</div>
		<p class="intro">{ng.settings_ai_stt_hint()}</p>
		<Card divided>
			<SettingRow
				title={ng.settings_ai_stt_base_url_label()}
				desc={locked.has('stt_base_url')
					? ng.settings_ai_env_locked()
					: ng.settings_ai_stt_base_url_tooltip()}
			>
				<input
					class="ctl"
					aria-label={ng.settings_ai_stt_base_url_label()}
					bind:value={sttBaseUrl}
					disabled={locked.has('stt_base_url')}
					aria-invalid={!!sttBaseUrl && !/^https?:\/\/.+/.test(sttBaseUrl)}
				/>
			</SettingRow>
			<SettingRow title={ng.settings_ai_stt_api_key_label()}>
				<div class="stack">
					<input
						class="ctl"
						type="password"
						autocomplete="off"
						aria-label={ng.settings_ai_stt_api_key_label()}
						bind:value={sttApiKey}
						disabled={locked.has('stt_api_key')}
						placeholder={status?.sttApiKeySet
							? ng.settings_ai_api_key_placeholder_set()
							: ng.settings_ai_api_key_placeholder_unset()}
					/>
					{#if status?.sttApiKeySet && !locked.has('stt_api_key')}
						<button class="link" onclick={() => clearKey('stt')}>
							{ng.settings_ai_api_key_clear()}
						</button>
					{/if}
				</div>
			</SettingRow>
			<SettingRow title={ng.settings_ai_stt_model_label()} desc={ng.settings_ai_stt_model_tooltip()}>
				<input
					class="ctl"
					aria-label={ng.settings_ai_stt_model_label()}
					bind:value={sttModel}
					disabled={locked.has('stt_model')}
				/>
			</SettingRow>
		</Card>

		<div class="actions">
			{#if !urlsValid}<span class="err">{ng.settings_ai_base_url_invalid()}</span>{/if}
			<Button variant="outline" disabled={probing} onclick={probe}>{ng.settings_ai_test()}</Button>
			<Button variant="primary" disabled={saving || !urlsValid} onclick={save}>
				{ng.buttons_save()}
			</Button>
		</div>

		{#if capabilities}
			<Card>
				<div class="probe">
					{#if capabilities.ok}
						<div class="probe-head">
							{ng.settings_ai_probe_reachable()}
							{#if capabilities.latencyMs != null}· {capabilities.latencyMs} ms{/if}
							· {capabilities.models.length}
							{ng.settings_ai_probe_models_listed()}
						</div>
						{#each [{ label: ng.settings_ai_probe_chat(), v: capabilities.chat }, { label: ng.settings_ai_probe_tools(), v: capabilities.tools }, { label: ng.settings_ai_probe_vision(), v: capabilities.vision }] as row (row.label)}
							<div class="tri">
								{#if row.v === 'yes'}<Check size={13} class="ok" />
								{:else if row.v === 'no'}<XIcon size={13} class="bad" />
								{:else}<Minus size={13} />{/if}
								<span>{row.label}: {TRI_LABEL[row.v]()}</span>
							</div>
						{/each}
					{:else}
						<div class="probe-head bad">{capabilities.error ?? ng.settings_ai_probe_failed()}</div>
					{/if}
				</div>
			</Card>
		{/if}

		{#if capabilities?.isOllama}
			<div class="sec-label">{ng.settings_ai_models_title()}</div>
			<p class="intro">{ng.settings_ai_models_hint()}</p>
			<Card divided>
				{#each OLLAMA_SUGGESTIONS as s (s.model)}
					<SettingRow
						title={s.model}
						desc={s.purpose === 'chat'
							? ng.settings_ai_models_purpose_chat()
							: ng.settings_ai_models_purpose_vision()}
					>
						{#if installed.includes(s.model)}
							<span class="installed">{ng.settings_ai_models_installed()}</span>
						{:else if pulling === s.model}
							<span class="installed">{pullPercent != null ? `${pullPercent}%` : '…'}</span>
						{:else}
							<Button variant="outline" disabled={!!pulling} onclick={() => pull(s.model)}>
								{ng.settings_ai_models_pull()}
							</Button>
						{/if}
					</SettingRow>
				{/each}
			</Card>
		{/if}

		<div class="sec-label">{ng.settings_ai_features_title()}</div>
		<p class="intro">{ng.settings_ai_features_hint()}</p>
		<Card divided>
			{#each FEATURES as f (f.key)}
				<SettingRow title={FEATURE_LABEL[f.key]()} desc={reasonText(f.key)}>
					<!-- A blocked feature shows no switch at all, and the row's description says why.
				     Upstream's Toggle has no disabled state, and a switch that silently refuses
				     is worse than an absent one with a reason beside it. A feature that is
				     blocked but already ON keeps its switch, so a prerequisite disappearing
				     cannot strand it enabled. -->
					{#if toggleDisabled(f, ready, flags[f.key] ?? false)}
						<span class="blocked">{ng.settings_ai_features_blocked()}</span>
					{:else}
						<Toggle
							checked={flags[f.key] ?? false}
							ariaLabel={FEATURE_LABEL[f.key]()}
							onchange={(v) => setFlag(f.key, v)}
						/>
					{/if}
				</SettingRow>
				{#if f.key === 'ai_feature_voice' && flags.ai_feature_voice}
					<SettingRow title={ng.settings_ai_features_voice_autosend()}>
						<Toggle
							checked={flags.ai_voice_autosend ?? false}
							ariaLabel={ng.settings_ai_features_voice_autosend()}
							onchange={(v) => setFlag('ai_voice_autosend', v)}
						/>
					</SettingRow>
				{/if}
			{/each}
		</Card>
	</section>
{/if}

<style>
	.sec-label {
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--text-dim);
		margin: 22px 0 8px;
	}
	.intro {
		margin: 0 0 10px;
		font-size: 12px;
		line-height: 1.55;
		color: var(--text-muted);
	}
	.ctl {
		width: 260px;
		max-width: 46vw;
		background: var(--input-bg);
		border: 1px solid var(--border-input);
		border-radius: var(--radius-sm);
		color: var(--text);
		padding: 6px 9px;
		font-size: 12.5px;
	}
	.ctl:focus {
		border-color: var(--accent);
	}
	.ctl[aria-invalid='true'] {
		border-color: var(--danger);
	}
	.ctl:disabled {
		opacity: 0.6;
	}
	.stack {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 4px;
	}
	.link {
		font-size: 11px;
		color: var(--accent-link);
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
	}
	.actions {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 10px;
		margin-top: 12px;
	}
	.err {
		flex: 1;
		font-size: 11.5px;
		color: var(--danger);
	}
	.probe {
		display: flex;
		flex-direction: column;
		gap: 5px;
		padding: 12px 14px;
		font-size: 12.5px;
	}
	.probe-head {
		font-weight: 600;
	}
	.probe-head.bad {
		color: var(--danger);
		font-weight: 400;
	}
	.tri {
		display: flex;
		align-items: center;
		gap: 6px;
		color: var(--text-muted);
	}
	.blocked {
		font-size: 11.5px;
		color: var(--text-dim);
	}
	.installed {
		font-size: 12px;
		color: var(--text-dim);
	}
</style>
