/**
 * Expand a link custom-field (#129) into a full URL: an admin defines a base-URL template once and
 * each item stores a short value, so the value doesn't have to be a whole URL.
 *
 * If the template contains a `{}` placeholder, the value is substituted there (so it can sit in the
 * middle of the URL); otherwise the value is appended to the template. The value is URL-encoded so
 * spaces and other characters are safe. An empty value yields an empty string (no link).
 */
export function buildLinkUrl(template: string, value: string): string {
  if (!value) return "";
  const encoded = encodeURIComponent(value);
  return template.includes("{}") ? template.replaceAll("{}", encoded) : template + encoded;
}
