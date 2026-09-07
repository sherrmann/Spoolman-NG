/**
 * Printers (#75 / #413): the wire-to-domain mapping and the form rules, kept apart from the
 * components so they can be tested without a DOM.
 */
import type { Printer } from './types';

type Json = Record<string, unknown>;

export const PRINTER_NAME_MAX = 64;
export const PRINTER_COMMENT_MAX = 1024;

/** Nullable fields are absent from the JSON rather than null; both read as "unset" here. */
export function mapPrinter(p: Json): Printer {
	return {
		id: Number(p.id),
		name: String(p.name ?? ''),
		comment: p.comment == null ? undefined : String(p.comment),
		registered: p.registered == null ? undefined : String(p.registered),
		spoolCount: p.spool_count == null ? undefined : Number(p.spool_count),
		extra: (p.extra as Record<string, string> | undefined) ?? {}
	};
}

/** The React form's rules: a name is required and column limits apply. Returns the failing field. */
export function validatePrinter(name: string, comment: string): 'name' | 'comment' | null {
	const n = name.trim();
	if (!n || n.length > PRINTER_NAME_MAX) return 'name';
	if (comment.trim().length > PRINTER_COMMENT_MAX) return 'comment';
	return null;
}

/**
 * What to send for a printer form. The comment is cleared with an explicit null on an edit;
 * on a create it is simply left out, since there is nothing to clear.
 */
export function printerBody(
	name: string,
	comment: string,
	editing: boolean
): { name: string; comment?: string | null } {
	const c = comment.trim();
	if (c) return { name: name.trim(), comment: c };
	return editing ? { name: name.trim(), comment: null } : { name: name.trim() };
}
