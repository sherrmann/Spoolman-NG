// Recommended Ollama models for the managed-pull section (#364, F2). Data, not code —
// like the provider presets: a curated shortlist so a user on a fresh Ollama can get a
// sensible model per feature and hardware tier without hunting the model library. Anything
// else can still be pulled with `ollama pull` directly — this list is a convenience, not a
// limit.
//
// The size field is named `downloadSizeGb` because that is all it is: for most models it also
// approximates the memory needed to run them, but the two genuinely diverge. Gemma's E-series
// offloads Per-Layer Embeddings, so `gemma4:e2b` is a 7.2 GB download that runs in 1.7 GB —
// showing a download size as if it were a hardware requirement would put people off a model
// their machine handles comfortably. If such a model is ever added here, give it a separate
// resident-size field rather than fudging this one.

export interface RecommendedModel {
  model: string; // the exact `ollama pull` name
  purpose: "chat" | "vision";
  tier: "small" | "standard" | "large";
  downloadSizeGb: number;
  note: string;
}

export const RECOMMENDED_MODELS: RecommendedModel[] = [
  {
    model: "llama3.2:3b",
    purpose: "chat",
    tier: "small",
    downloadSizeGb: 2.0,
    note: "Chat & natural-language search on a Raspberry Pi 4/5 or low-RAM box.",
  },
  {
    model: "granite4.1:3b",
    purpose: "chat",
    tier: "small",
    downloadSizeGb: 2.1,
    note: "Fast and fits a 4 GB GPU entirely. Has no thinking mode, so nothing can slow it down.",
  },
  {
    // The `-instruct` suffix is load-bearing: measured against the 19-tool layer, plain `qwen3:4b`
    // scores 76% at ~21 s/call where `qwen3:4b-instruct` scores 91% at ~1.9 s (#380).
    model: "qwen3:4b-instruct",
    purpose: "chat",
    tier: "small",
    downloadSizeGb: 2.5,
    note: "Best measured tool-calling for its size. Note the -instruct suffix; plain qwen3:4b is much slower.",
  },
  {
    model: "qwen3:8b",
    purpose: "chat",
    tier: "standard",
    downloadSizeGb: 5.2,
    note: "Larger chat model. Wants ~6 GB of VRAM; below that it spills to CPU and gets very slow.",
  },
  {
    model: "qwen2.5vl:7b",
    purpose: "vision",
    tier: "standard",
    downloadSizeGb: 6.0,
    note: "Best measured label reader for Scan-to-Spool. Runs on CPU too, just slower.",
  },
  {
    model: "llama3.2-vision:11b",
    purpose: "vision",
    tier: "large",
    downloadSizeGb: 7.9,
    note: "Larger vision model; needs a capable GPU or plenty of RAM.",
  },
];
