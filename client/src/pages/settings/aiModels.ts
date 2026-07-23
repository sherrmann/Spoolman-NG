// Recommended-model table for the managed pull (#364 F2). Data, not code - like the
// provider presets. Sizes are approximate download sizes shown BEFORE pulling; tags
// are Ollama library tags. Curated small on purpose: one small/standard pick per
// capability, not a catalog.

export interface RecommendedModel {
  /** Ollama model tag, exactly as pulled. */
  model: string;
  /** Approximate download size in GB, shown before pulling. */
  sizeGB: number;
  /** i18n key describing what the model is for. */
  purposeKey: string;
  /** Suited to Pi-5-class (arm64) hardware. */
  small?: boolean;
  /** Vision-capable (Scan-to-Spool). */
  vision?: boolean;
}

export const RECOMMENDED_MODELS: RecommendedModel[] = [
  { model: "qwen3:4b", sizeGB: 2.6, purposeKey: "settings.ai.models.purpose_chat_small", small: true },
  { model: "qwen3:8b", sizeGB: 5.2, purposeKey: "settings.ai.models.purpose_chat" },
  {
    model: "qwen2.5vl:3b",
    sizeGB: 3.2,
    purposeKey: "settings.ai.models.purpose_vision_small",
    small: true,
    vision: true,
  },
  { model: "qwen2.5vl:7b", sizeGB: 6.0, purposeKey: "settings.ai.models.purpose_vision", vision: true },
];
