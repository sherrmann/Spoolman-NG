/**
 * Expand a `link` extra-field (#129) into a full URL: an administrator defines a base-URL
 * template once on the field definition and each item stores only a short value, so the value
 * does not have to be a whole URL.
 *
 * If the template contains a `{}` placeholder the value is substituted there (so it can sit in
 * the middle of the URL); otherwise the value is appended to the template. The value is
 * URL-encoded, so spaces and separators are safe. An empty value yields an empty string, which
 * the caller renders as plain text rather than as a link to nowhere.
 *
 * Ported verbatim from the React client's `client/src/utils/linkField.ts` so both clients expand
 * the same stored value to the same URL.
 */
export function buildLinkUrl(template: string, value: string): string {
	if (!value) return '';
	const encoded = encodeURIComponent(value);
	return template.includes('{}') ? template.replaceAll('{}', encoded) : template + encoded;
}
