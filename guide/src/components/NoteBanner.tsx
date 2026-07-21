import type { Note } from "../model/types";

export function NoteBanner({ note }: { note: Note }) {
  return (
    <p className={`note note-${note.level}`} role={note.level === "warning" ? "alert" : "note"}>
      <span className="note-icon" aria-hidden="true">
        {note.level === "warning" ? "⚠" : "ℹ"}
      </span>
      {note.text}
    </p>
  );
}
