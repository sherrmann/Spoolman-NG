import { useState } from "react";

interface Props {
  content: string;
  language: string;
  title?: string;
  filename?: string;
}

export function CodeBlock({ content, language, title, filename }: Props) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API unavailable (e.g. non-secure context) — leave the button as-is;
      // the text remains selectable.
    }
  }

  return (
    <figure className="code-block" data-language={language}>
      {(title || filename) && (
        <figcaption>
          <span className="code-title">{title ?? filename}</span>
          {filename && title && filename !== title && <code className="code-filename">{filename}</code>}
        </figcaption>
      )}
      <div className="code-body">
        <button type="button" className="copy-button" onClick={copy} aria-label="Copy to clipboard">
          {copied ? "Copied ✓" : "Copy"}
        </button>
        <pre>
          <code>{content}</code>
        </pre>
      </div>
    </figure>
  );
}
