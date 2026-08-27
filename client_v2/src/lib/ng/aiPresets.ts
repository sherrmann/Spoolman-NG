/**
 * Providers whose base URL is worth not making the operator look up.
 *
 * Pure data, ported from the React client. Picking one fills the URL field in and nothing else:
 * the model still has to be chosen, and a hosted provider still needs a key. That is deliberate
 * -- a preset that silently configured more than one field would be guessing on the operator's
 * behalf about the thing most likely to be wrong.
 */
export interface AiPreset {
	key: string;
	label: string;
	baseUrl: string;
	/** Hosted providers refuse anonymous requests; local ones ignore the key entirely. */
	needsKey: boolean;
}

export const AI_PRESETS: AiPreset[] = [
	{ key: 'ollama', label: 'Ollama', baseUrl: 'http://localhost:11434/v1', needsKey: false },
	{ key: 'lmstudio', label: 'LM Studio', baseUrl: 'http://localhost:1234/v1', needsKey: false },
	{ key: 'openai', label: 'OpenAI', baseUrl: 'https://api.openai.com/v1', needsKey: true },
	{ key: 'anthropic', label: 'Anthropic', baseUrl: 'https://api.anthropic.com/v1', needsKey: true },
	{ key: 'openrouter', label: 'OpenRouter', baseUrl: 'https://openrouter.ai/api/v1', needsKey: true },
	{ key: 'requesty', label: 'Requesty', baseUrl: 'https://router.requesty.ai/v1', needsKey: true },
	{ key: 'groq', label: 'Groq', baseUrl: 'https://api.groq.com/openai/v1', needsKey: true },
	{ key: 'mistral', label: 'Mistral', baseUrl: 'https://api.mistral.ai/v1', needsKey: true },
	{
		key: 'gemini',
		label: 'Gemini',
		baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
		needsKey: true
	}
];

/** Models worth offering to pull on an Ollama endpoint, and what each is for. */
export const OLLAMA_SUGGESTIONS: { model: string; purpose: 'chat' | 'vision' }[] = [
	{ model: 'qwen3:8b', purpose: 'chat' },
	{ model: 'llama3.1:8b', purpose: 'chat' },
	{ model: 'qwen2.5vl:7b', purpose: 'vision' }
];
