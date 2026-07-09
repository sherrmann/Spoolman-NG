import { ISpool } from "../pages/spools/model";
import { CustomLink, parseCustomLinks } from "./customLinks";
import { useGetSetting } from "./querySettings";

// Fields from a spool that a per-spool action link (#140) may template in, e.g. {id} or {location}.
// A known token is substituted (URL-encoded); an unknown token resolves to an empty string.
function spoolTokens(spool: ISpool): Record<string, string | number | undefined> {
  return {
    id: spool.id,
    filament_id: spool.filament?.id,
    location: spool.location,
    lot_nr: spool.lot_nr,
    comment: spool.comment,
  };
}

/**
 * Expand a per-spool action-link template (#140) by replacing `{field}` tokens with the spool's
 * values (URL-encoded). Unknown tokens resolve to an empty string, so a template with a typo yields
 * a harmless truncated URL rather than a literal brace.
 */
export function buildSpoolActionUrl(template: string, spool: ISpool): string {
  const tokens = spoolTokens(spool);
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => {
    const value = tokens[key];
    return value === undefined || value === null ? "" : encodeURIComponent(String(value));
  });
}

/** Read the configured per-spool action links (#140) from settings. */
export function useSpoolActionLinks(): CustomLink[] {
  const setting = useGetSetting("spool_action_links");
  return parseCustomLinks(setting.data?.value);
}
