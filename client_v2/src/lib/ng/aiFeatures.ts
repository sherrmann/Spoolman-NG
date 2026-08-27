/**
 * Which AI features an operator may switch on, and why not when they may not.
 *
 * Every feature is a plain boolean setting, so nothing stops one being enabled before the thing
 * it needs exists -- turning on voice with no speech-to-text endpoint gives a microphone that
 * answers 409 on every press. The panel therefore has to explain a blocked toggle rather than
 * merely disabling it, and this module is where that reasoning lives, away from the markup and
 * testable on its own.
 *
 * The rule worth stating: a blocked feature can always be switched OFF, never on. Blocking the
 * off direction would strand a feature that was enabled before its prerequisite disappeared --
 * exactly when an operator most wants to turn it off.
 */

export type FeatureKey =
	| 'ai_feature_chat'
	| 'ai_feature_voice'
	| 'ai_feature_nl_search'
	| 'ai_feature_scan_to_spool'
	| 'ai_feature_mcp';

/** Why a feature cannot be switched on, or null when it can. */
export type BlockedReason =
	/** No endpoint and chat model saved yet. */
	| 'requires_config'
	/** No speech-to-text endpoint and model saved yet. */
	| 'requires_stt'
	/** The capability probe says the configured model cannot see images. */
	| 'requires_vision';

export interface FeatureDef {
	key: FeatureKey;
	/** Needs an endpoint and chat model. MCP does not: it exposes tools, it calls no model. */
	needsProvider: boolean;
	needsStt?: boolean;
	needsVision?: boolean;
	/**
	 * True when this client has no UI for the feature. It is NOT a reason to block the toggle:
	 * the setting is server-wide and the React client does implement it, so switching it on here
	 * is a legitimate thing to do -- it just will not change anything in this client.
	 */
	absentHere?: boolean;
}

export const FEATURES: FeatureDef[] = [
	{ key: 'ai_feature_chat', needsProvider: true },
	{ key: 'ai_feature_voice', needsProvider: false, needsStt: true },
	{ key: 'ai_feature_nl_search', needsProvider: true },
	// Photo intake: a React-client page with no Svelte equivalent yet.
	{ key: 'ai_feature_scan_to_spool', needsProvider: true, needsVision: true, absentHere: true },
	// MCP is a server the operator points a client at; it needs no LLM of its own.
	{ key: 'ai_feature_mcp', needsProvider: false, absentHere: true }
];

export interface Readiness {
	configured: boolean;
	sttConfigured: boolean;
	/** From the probe. 'unknown' must not block: most endpoints cannot report capabilities. */
	vision: 'yes' | 'no' | 'unknown';
}

/** Why `feature` cannot be turned on right now, or null if it can. */
export function blockedReason(feature: FeatureDef, ready: Readiness): BlockedReason | null {
	if (feature.needsProvider && !ready.configured) return 'requires_config';
	if (feature.needsStt && !ready.sttConfigured) return 'requires_stt';
	// Only a definite "no" blocks. An endpoint that does not report capabilities returns
	// 'unknown', and refusing on that would make the feature unreachable on every provider
	// except Ollama.
	if (feature.needsVision && ready.vision === 'no') return 'requires_vision';
	return null;
}

/**
 * Whether the toggle should be inert.
 *
 * `enabled` is its current value: a blocked feature that is already on stays operable so it can
 * be turned off.
 */
export function toggleDisabled(feature: FeatureDef, ready: Readiness, enabled: boolean): boolean {
	return !enabled && blockedReason(feature, ready) !== null;
}
