// Provider presets for the Settings -> AI tab (#359). Presets are data, not code
// (docs/llm-integration-brainstorm.md §5 decision 5): every entry is just a label, a
// base URL, and whether the provider needs an API key. Anything OpenAI-compatible
// works via "Custom" — adding a provider here is a convenience, never a requirement.

export interface AIPreset {
  key: string;
  label: string;
  baseUrl: string;
  needsKey: boolean;
}

export const AI_PRESETS: AIPreset[] = [
  { key: "ollama", label: "Ollama", baseUrl: "http://localhost:11434/v1", needsKey: false },
  { key: "lmstudio", label: "LM Studio", baseUrl: "http://localhost:1234/v1", needsKey: false },
  { key: "openai", label: "OpenAI", baseUrl: "https://api.openai.com/v1", needsKey: true },
  // Anthropic's official OpenAI-SDK compatibility endpoint over the Claude API.
  { key: "anthropic", label: "Anthropic", baseUrl: "https://api.anthropic.com/v1", needsKey: true },
  { key: "openrouter", label: "OpenRouter", baseUrl: "https://openrouter.ai/api/v1", needsKey: true },
  { key: "requesty", label: "Requesty", baseUrl: "https://router.requesty.ai/v1", needsKey: true },
  { key: "groq", label: "Groq", baseUrl: "https://api.groq.com/openai/v1", needsKey: true },
  { key: "mistral", label: "Mistral", baseUrl: "https://api.mistral.ai/v1", needsKey: true },
  {
    key: "gemini",
    label: "Gemini",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai",
    needsKey: true,
  },
];
