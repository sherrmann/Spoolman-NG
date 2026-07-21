export interface Note {
  level: "warning" | "info";
  id: string;
  text: string;
}

export interface Artifact {
  id: string;
  /** Suggested filename when the user saves the block. */
  filename: string;
  /** Highlighting/display hint: yaml, ini, bash, caddy, nginx, dotenv. */
  language: string;
  /** Human title shown above the code block. */
  title: string;
  content: string;
}

export interface Step {
  id: string;
  title: string;
  /** Prose for the step; plain text with inline `code` allowed. */
  body?: string;
  /** Shell commands rendered as one copyable block. */
  commands?: string[];
  /** Non-shell inline snippet (e.g. a YAML excerpt to edit into an existing file). */
  code?: { language: string; content: string };
  /** Artifacts (by id) that belong to this step. */
  artifactIds?: string[];
  notes?: Note[];
}

export interface Plan {
  steps: Step[];
  artifacts: Artifact[];
  /** Plan-wide warnings/info, shown above the steps. */
  warnings: Note[];
}
