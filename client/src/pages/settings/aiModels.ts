// Recommended Ollama models for the managed-pull section (#364, F2). Data, not code —
// like the provider presets: a curated shortlist so a user on a fresh Ollama can get a
// sensible model per feature and hardware tier without hunting the model library. Sizes
// are approximate download sizes (GB) for the default quantisation. Anything else can
// still be pulled with `ollama pull` directly — this list is a convenience, not a limit.

export interface RecommendedModel {
  model: string; // the exact `ollama pull` name
  purpose: "chat" | "vision";
  tier: "small" | "standard" | "large";
  sizeGb: number;
  note: string;
}

export const RECOMMENDED_MODELS: RecommendedModel[] = [
  {
    model: "llama3.2:3b",
    purpose: "chat",
    tier: "small",
    sizeGb: 2.0,
    note: "Chat & natural-language search on a Raspberry Pi 4/5 or low-RAM box.",
  },
  {
    model: "qwen3:4b",
    purpose: "chat",
    tier: "small",
    sizeGb: 2.6,
    note: "Stronger small chat model; good tool-calling for its size.",
  },
  {
    model: "qwen3:8b",
    purpose: "chat",
    tier: "standard",
    sizeGb: 5.2,
    note: "The default recommendation for chat/tool features on a desktop or NAS.",
  },
  {
    model: "qwen2.5vl:7b",
    purpose: "vision",
    tier: "standard",
    sizeGb: 6.0,
    note: "Vision model for Scan-to-Spool label reading.",
  },
  {
    model: "llama3.2-vision:11b",
    purpose: "vision",
    tier: "large",
    sizeGb: 7.9,
    note: "Larger vision model; needs a capable GPU or plenty of RAM.",
  },
];
