import { describe, expect, it } from 'vitest';
import { FEATURES, blockedReason, toggleDisabled, type FeatureDef, type Readiness } from './aiFeatures';

const feature = (key: string): FeatureDef => FEATURES.find((f) => f.key === key)!;
const ready = (over: Partial<Readiness> = {}): Readiness => ({
	configured: true,
	sttConfigured: true,
	vision: 'yes',
	...over
});

describe('blockedReason', () => {
	it('blocks a provider feature until an endpoint and model are saved', () => {
		expect(blockedReason(feature('ai_feature_chat'), ready({ configured: false }))).toBe('requires_config');
	});

	it('blocks voice until speech-to-text is configured, not merely until the provider is', () => {
		// Voice needs no chat provider at all -- it needs a transcription endpoint, which is a
		// separate setting. Blocking it on the wrong one sends the operator to the wrong field.
		expect(
			blockedReason(feature('ai_feature_voice'), ready({ configured: false, sttConfigured: true }))
		).toBeNull();
		expect(blockedReason(feature('ai_feature_voice'), ready({ sttConfigured: false }))).toBe('requires_stt');
	});

	it('lets MCP be enabled with no provider at all', () => {
		// MCP exposes tools to someone else's client; it calls no model of its own.
		expect(
			blockedReason(feature('ai_feature_mcp'), ready({ configured: false, sttConfigured: false }))
		).toBeNull();
	});

	it('blocks a vision feature only on a definite no', () => {
		const scan = feature('ai_feature_scan_to_spool');
		expect(blockedReason(scan, ready({ vision: 'no' }))).toBe('requires_vision');
		// 'unknown' is what every endpoint that cannot report capabilities returns. Treating it
		// as "no" would make the feature unreachable on everything except Ollama.
		expect(blockedReason(scan, ready({ vision: 'unknown' }))).toBeNull();
		expect(blockedReason(scan, ready({ vision: 'yes' }))).toBeNull();
	});

	it('reports the first unmet requirement, so the operator has one thing to fix', () => {
		expect(
			blockedReason(feature('ai_feature_scan_to_spool'), ready({ configured: false, vision: 'no' }))
		).toBe('requires_config');
	});
});

describe('toggleDisabled', () => {
	it('lets a blocked feature that is already on be switched off', () => {
		// The case this rule exists for: a prerequisite disappeared after the feature was
		// enabled. Freezing the toggle would strand it on exactly when it needs turning off.
		expect(toggleDisabled(feature('ai_feature_voice'), ready({ sttConfigured: false }), true)).toBe(false);
	});

	it('keeps a blocked feature that is off from being switched on', () => {
		expect(toggleDisabled(feature('ai_feature_voice'), ready({ sttConfigured: false }), false)).toBe(true);
	});

	it('leaves an unblocked feature operable either way', () => {
		expect(toggleDisabled(feature('ai_feature_chat'), ready(), false)).toBe(false);
		expect(toggleDisabled(feature('ai_feature_chat'), ready(), true)).toBe(false);
	});
});

describe('the feature list', () => {
	it('marks the features this client has no UI for', () => {
		// Not a reason to block them: the setting is server-wide and the React client does
		// implement them, so enabling one here is legitimate -- it just changes nothing here.
		expect(feature('ai_feature_scan_to_spool').absentHere).toBe(true);
		expect(feature('ai_feature_mcp').absentHere).toBe(true);
		expect(feature('ai_feature_chat').absentHere).toBeUndefined();
		expect(feature('ai_feature_voice').absentHere).toBeUndefined();
		expect(feature('ai_feature_nl_search').absentHere).toBeUndefined();
	});
});
