import { expect, type Locator, type Page } from "@playwright/test";
import { layoutProblems } from "../mobile/layout";

/**
 * Checks for how a rendered page holds up on a given device, beyond the layout checks in
 * ../mobile/layout.ts (sideways scroll, controls pushed or clipped out of reach). Each one looks
 * for a defect a user of that device actually meets, measured from the DOM:
 *
 * - Tap targets too small to hit with a finger. WCAG 2.2 (SC 2.5.8) sets the floor at 24x24 CSS
 *   px, or enough space around a smaller target that a 24px circle on it touches no other. Only
 *   asked of touch devices; a mouse can hit a 16px icon.
 * - A control that is covered: something else is drawn over its centre even after it is scrolled
 *   into view, so a tap lands on the wrong thing. A floating button parked over a row's actions,
 *   or content that ends under the phone's bottom bar, look exactly like this.
 * - Styles outside upstream's design language: a font that is not one of the --font-* tokens, a
 *   weight heavier than upstream ever uses, or text in a colour that is not one of the theme's
 *   tokens (so it cannot follow the light/dark switch). The static twin of this check is
 *   client_v2/src/lib/ng/designLanguage.test.ts; this one sees the cascade as the browser
 *   resolved it, including upstream's own pages.
 */

export interface Problem {
  kind: "tap-target-too-small" | "control-covered" | "off-design-style";
  detail: string;
}

interface Options {
  /** Check tap-target size; for touch devices. */
  touch: boolean;
  /** Only look inside this element (a dialog), not the whole page. */
  scope?: string;
  /** Selectors whose elements are exempt from the tap-target size rule (see UPSTREAM_TAP_TARGETS). */
  waive?: string[];
}

/** Runs in the page. Self-contained so Playwright can serialise it. */
function collect({ touch, scope, waive = [] }: Options): Problem[] {
  const problems: Problem[] = [];
  // The last match is the one on top: a dialog opened from inside another comes after it.
  const scoped = scope ? Array.from(document.querySelectorAll(scope)) : [];
  const root: Element = scoped[scoped.length - 1] ?? document.body;
  const vw = document.documentElement.clientWidth;
  const vh = document.documentElement.clientHeight;
  const MIN = 24;

  const describe = (el: Element): string => {
    const cls = typeof (el as HTMLElement).className === "string" ? (el as HTMLElement).className : "";
    const firstClass = cls
      .trim()
      .split(/\s+/)
      .filter((c) => c && !c.startsWith("svelte-"))[0];
    const label =
      el.getAttribute("aria-label") ||
      el.getAttribute("title") ||
      (el as HTMLInputElement).placeholder ||
      (el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 30);
    return `<${el.tagName.toLowerCase()}${firstClass ? "." + firstClass : ""}>${label ? ` "${label}"` : ""}`;
  };
  // Memoised: the design pass below asks this of every element, and the ancestors repeat.
  const hiddenTree = new Map<Element, boolean>();
  const treeHidden = (el: Element | null): boolean => {
    if (!el) return false;
    let v = hiddenTree.get(el);
    if (v === undefined) {
      const s = getComputedStyle(el);
      v = s.display === "none" || s.visibility === "hidden" || s.opacity === "0" || treeHidden(el.parentElement);
      hiddenTree.set(el, v);
    }
    return v;
  };
  const isShown = (el: Element): boolean => {
    if (treeHidden(el)) return false;
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  };

  const CONTROLS =
    'a[href], button, input:not([type="hidden"]), select, textarea, summary, [role="button"], ' +
    '[role="tab"], [role="checkbox"], [role="switch"], [role="menuitem"], [role="option"]';
  const controls = Array.from(root.querySelectorAll(CONTROLS)).filter(
    (el) =>
      isShown(el) &&
      !(el as HTMLButtonElement).disabled &&
      getComputedStyle(el).pointerEvents !== "none" &&
      // Click-outside catchers: full-screen, deliberately unfocusable, hidden from AT.
      !(el.getAttribute("aria-hidden") === "true" && el.getAttribute("tabindex") === "-1"),
  );

  /**
   * The box a finger actually hits. A control inside a <label> is hit through the label, and a
   * "stretched" link -- an absolutely positioned ::after laid over its whole row, the pattern the
   * fork's list pages use so a row with buttons in it can still be one link -- through that row.
   */
  const targetOf = (el: Element): DOMRect => {
    let best = el.getBoundingClientRect();
    const bigger = (r: DOMRect) => {
      if (r.width * r.height > best.width * best.height) best = r;
    };
    const label = el.closest("label");
    if (label) bigger(label.getBoundingClientRect());
    for (const pseudo of ["::after", "::before"]) {
      const ps = getComputedStyle(el, pseudo);
      if (ps.content === "none" || ps.position !== "absolute") continue;
      let block = el.parentElement;
      while (block && getComputedStyle(block).position === "static") block = block.parentElement;
      if (block) bigger(block.getBoundingClientRect());
    }
    return best;
  };
  /** A link inside running text is exempt from the size rule (SC 2.5.8 "inline"). */
  const isInline = (el: Element) => {
    if (el.tagName !== "A") return false;
    if (getComputedStyle(el).display !== "inline") return false;
    const parent = el.parentElement;
    return !!parent && Array.from(parent.childNodes).some((n) => n.nodeType === 3 && n.textContent!.trim());
  };

  if (touch) {
    const boxes = controls.map((el) => ({ el, r: targetOf(el) }));
    for (const { el, r } of boxes) {
      if (r.width >= MIN && r.height >= MIN) continue;
      if (isInline(el)) continue;
      if (waive.some((sel) => el.matches(sel))) continue;
      // Spacing exception: a 24px circle on this target's centre must not touch another's.
      const cx = r.left + r.width / 2;
      const cy = r.top + r.height / 2;
      const crowded = boxes.some(({ el: o, r: or }) => {
        if (o === el || o.contains(el) || el.contains(o)) return false;
        const nx = Math.max(or.left, Math.min(cx, or.right));
        const ny = Math.max(or.top, Math.min(cy, or.bottom));
        const small = or.width < MIN || or.height < MIN;
        // Against another undersized target both circles count; against a full-size one, only ours.
        return Math.hypot(nx - cx, ny - cy) < (small ? MIN : MIN / 2);
      });
      if (crowded) {
        problems.push({
          kind: "tap-target-too-small",
          detail: `${describe(el)} is ${Math.round(r.width)}x${Math.round(r.height)}px with another target too close`,
        });
      }
    }
  }

  // Covered controls. Scroll each into view first, so something that is merely below the fold
  // (or under a fixed bar until scrolled) is not reported; restore every scroll afterwards.
  const scrolled = new Map<Element, [number, number]>();
  const remember = (el: Element) => {
    for (let a: Element | null = el; a; a = a.parentElement) {
      if (!scrolled.has(a)) scrolled.set(a, [a.scrollLeft, a.scrollTop]);
    }
  };
  const winScroll: [number, number] = [window.scrollX, window.scrollY];
  const isFloating = (el: Element) => {
    for (let a: Element | null = el; a; a = a.parentElement) {
      const p = getComputedStyle(a).position;
      if (p === "fixed" || p === "sticky") return true;
    }
    return false;
  };
  // Forty identical rows share one layout, and scrolling each into view is the slow part (a
  // large board has hundreds of chips): check the first two of each kind -- same tag and classes,
  // under a parent with the same classes -- and the last, rather than every one. The last matters:
  // content that ends under the bottom bar only hides the end of a list.
  const kindOf = (el: Element) => `${el.tagName}.${el.className}<${el.parentElement?.className ?? ""}`;
  const lastOfKind = new Map<string, Element>();
  for (const el of controls) lastOfKind.set(kindOf(el), el);
  const kinds = new Map<string, number>();
  for (const el of controls) {
    const kind = kindOf(el);
    const n = kinds.get(kind) ?? 0;
    kinds.set(kind, n + 1);
    if (n >= 2 && lastOfKind.get(kind) !== el) continue;
    // A screen-sized backdrop (the inspector sheet's scrim) sits behind what it dims by design.
    const whole = el.getBoundingClientRect();
    if (whole.width >= vw * 0.9 && whole.height >= vh * 0.9) continue;
    remember(el);
    el.scrollIntoView({ block: "center", inline: "nearest" });
    const r = el.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    if (cx < 0 || cy < 0 || cx >= vw || cy >= vh) continue;
    // Still clipped by a scrolling ancestor (a strip scrolled away): not reachable here, and the
    // layout check already speaks for reachability.
    let clipped = false;
    for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
      const s = getComputedStyle(a);
      if (s.overflowX === "visible" && s.overflowY === "visible") continue;
      const ar = a.getBoundingClientRect();
      if (cx < ar.left || cx > ar.right || cy < ar.top || cy > ar.bottom) clipped = true;
    }
    if (clipped) continue;
    // Covered means no part of it can be tapped: sample a grid over the box, not only the
    // centre, so a row link with a raised button over part of it is not reported.
    let reachable = false;
    let blocker: Element | null = null;
    for (const fx of [0.5, 0.2, 0.8]) {
      for (const fy of [0.5, 0.25, 0.75]) {
        const x = r.left + r.width * fx;
        const y = r.top + r.height * fy;
        if (x < 0 || y < 0 || x >= vw || y >= vh) continue;
        const hit = document.elementFromPoint(x, y);
        if (!hit) continue;
        const label = hit.closest("label");
        if (
          hit === el ||
          el.contains(hit) ||
          (label && (label.contains(el) || (label as HTMLLabelElement).control === el)) ||
          // Hit through a non-floating ancestor: the control is transparent to hit testing at
          // that point but sits inside what was hit, so the tap still lands on its row.
          (hit.contains(el) && !isFloating(hit))
        ) {
          reachable = true;
          break;
        }
        blocker ??= hit;
      }
      if (reachable) break;
    }
    if (reachable || !blocker) continue;
    problems.push({
      kind: "control-covered",
      detail: `${describe(el)} is covered by ${describe(blocker)}${isFloating(blocker) ? " (fixed)" : ""}`,
    });
  }
  for (const [el, [x, y]] of scrolled) {
    el.scrollLeft = x;
    el.scrollTop = y;
  }
  window.scrollTo(winScroll[0], winScroll[1]);

  // Design language. Token values are resolved by the browser, so both themes are covered by
  // whichever one is active.
  const rootStyle = getComputedStyle(document.documentElement);
  const tokenNames = new Set<string>();
  for (const sheet of Array.from(document.styleSheets)) {
    let rules: CSSRuleList;
    try {
      rules = sheet.cssRules;
    } catch {
      continue; // cross-origin (the font CDN)
    }
    const walk = (list: CSSRuleList) => {
      for (const rule of Array.from(list)) {
        if ("cssRules" in rule && (rule as CSSGroupingRule).cssRules) walk((rule as CSSGroupingRule).cssRules);
        const style = (rule as CSSStyleRule).style;
        if ((rule as CSSStyleRule).selectorText?.includes(":root") && style) {
          for (const name of Array.from(style)) if (name.startsWith("--")) tokenNames.add(name);
        }
      }
    };
    walk(rules);
  }
  const probe = document.createElement("span");
  document.body.appendChild(probe);
  const palette = new Set<string>(["rgb(255, 255, 255)", "rgb(0, 0, 0)"]);
  for (const name of tokenNames) {
    probe.style.color = "";
    probe.style.color = `var(${name})`;
    const c = getComputedStyle(probe).color;
    if (c) palette.add(c);
  }
  probe.remove();
  const fonts = ["--font-sans", "--font-mono"].map((t) => rootStyle.getPropertyValue(t).trim().split(",")[0]);
  const sameFamily = (family: string) => fonts.some((f) => f && family.split(",")[0].trim() === f.trim());

  const seen = new Set<string>();
  const report = (el: Element, what: string) => {
    const line = `${describe(el)} ${what}`;
    if (seen.has(line)) return;
    seen.add(line);
    problems.push({ kind: "off-design-style", detail: line });
  };
  for (const el of Array.from(root.querySelectorAll("*"))) {
    if (el.closest("svg, canvas, [data-design-exempt]")) continue;
    const ownText = Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent!.trim());
    if (!ownText || !isShown(el)) continue;
    const s = getComputedStyle(el);
    if (!sameFamily(s.fontFamily)) report(el, `uses font ${s.fontFamily.split(",")[0]}`);
    if (Number(s.fontWeight) > 700) report(el, `uses weight ${s.fontWeight}`);
    // A colour written on the element itself is data (a filament's colour), not styling.
    if (!(el as HTMLElement).style.color && !palette.has(s.color)) report(el, `uses colour ${s.color}`);
  }
  return problems;
}

export function deviceProblems(page: Page, options: Options): Promise<Problem[]> {
  return page.evaluate(collect, options);
}

/**
 * Known small tap targets in components this fork vendors from upstream (client_v2 is a subtree;
 * editing these files costs a merge conflict on every pull -- see
 * docs/upstream/client-v2-fork-additions.md). Each is upstream's deliberate density, most of it
 * named in the comment above app.css's touch-target rule ("intentionally-dense inline editors in
 * the inspector are left as-is by design").
 *
 * Each selector follows the owning component's own markup, not just a class name, because fork
 * components reuse some of upstream's class names (`.trigger`, `.link`, `.toggle`); a fork
 * component that copies one of these structures is excluded by name. Evaluated in the page with
 * `Element.matches`, so an element is waived only if it really sits in that structure.
 *
 * Only tap-target sizes are waived. Layout, covered-control and design problems never are.
 */
export const UPSTREAM_TAP_TARGETS: { selector: string; owner: string }[] = [
  { selector: ".card-head .grip, .card-head .card-name", owner: "routes/dashboard/+page.svelte" },
  { selector: ".ni > .spin > button", owner: "components/NumberInput.svelte (stacked steppers)" },
  { selector: "input.edit", owner: "components/EditableField.svelte (inline editor)" },
  { selector: "input.cbx", owner: "components/Combobox.svelte (inline editor)" },
  { selector: ".dtf > button.trigger", owner: "components/DateTimeField.svelte (inline editor)" },
  { selector: "button.help-toggle", owner: "components/Field.svelte (field help icon)" },
  { selector: "a.manage", owner: "components/ExtraFieldsSection.svelte" },
  {
    // FilamentImageSection (fork) renders the same .sec-actions > .link structure.
    selector: ".sec-actions > .link:not(.photo-section *)",
    owner: "library/SpoolInspector.svelte, library/VendorSection.svelte",
  },
  {
    // Includes the fork's "Encode to NFC" beside upstream's "Add tag", written in the same style.
    selector: ".section > .right > button.link",
    owner: "components/TagsSection.svelte",
  },
  { selector: 'button.toggle[role="switch"]', owner: "components/Toggle.svelte" },
  { selector: "a.doclink", owner: "routes/settings/+page.svelte" },
  { selector: "button.sort-dir-btn", owner: "components/library/ListToolbar.svelte" },
];

/**
 * Every problem on the page, or inside `scope`, as rendered now: the layout checks from
 * ../mobile/layout.ts plus the device checks above. Identical lines are counted, not repeated.
 */
export async function expectDeviceReady(page: Page, where: string, options: Options): Promise<void> {
  const lines: string[] = [];
  for (const p of await layoutProblems(page)) lines.push(`${p.kind}: ${p.detail}`);
  for (const p of await deviceProblems(page, { ...options, waive: UPSTREAM_TAP_TARGETS.map((k) => k.selector) })) {
    lines.push(`${p.kind}: ${p.detail}`);
  }
  const counts = new Map<string, number>();
  for (const line of lines) counts.set(line, (counts.get(line) ?? 0) + 1);
  expect(
    [...counts].map(([line, n]) => (n > 1 ? `${line} (x${n})` : line)),
    `problems on ${where} at ${page.viewportSize()?.width}x${page.viewportSize()?.height}`,
  ).toEqual([]);
}

/** The open dialog fits the screen: fully inside the viewport, or scrollable within it. */
export async function expectDialogFits(page: Page, dialog: Locator, what: string): Promise<void> {
  await expect(dialog).toBeVisible();
  const box = (await dialog.boundingBox())!;
  const vp = page.viewportSize()!;
  expect(box.x, `${what} starts left of the screen`).toBeGreaterThanOrEqual(-1);
  expect(box.x + box.width, `${what} runs off the right edge`).toBeLessThanOrEqual(vp.width + 1);
  expect(box.y, `${what} starts above the screen`).toBeGreaterThanOrEqual(-1);
  expect(box.y + box.height, `${what} runs off the bottom`).toBeLessThanOrEqual(vp.height + 1);
}
