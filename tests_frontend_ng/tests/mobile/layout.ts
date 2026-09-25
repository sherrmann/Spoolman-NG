import { expect, type Page } from "@playwright/test";

/**
 * Layout checks for phone-sized screens.
 *
 * Each check looks for a defect a phone user actually hits, measured from the rendered DOM rather
 * than from class names, so it keeps working when the styling is reorganised:
 *
 * - The page scrolls sideways. On a phone the whole UI then slides under the finger on every
 *   vertical swipe.
 * - A control is pushed or clipped out of reach. Two shapes: off the screen's side with no way to
 *   scroll to it, or cut off by an ancestor that hides its overflow. A fixed-width input in a
 *   narrow column did exactly this to the inspector's +/- steppers.
 * - A vertical scroller that also scrolls sideways. That is almost always an accident (something
 *   inside is wider than the column) and the sideways part is invisible until a diagonal swipe.
 *
 * Horizontal strips -- a scroller that does not scroll vertically, like the mobile tab row -- are
 * deliberate, so a control inside one only has to be reachable by scrolling the strip.
 */

export interface LayoutProblem {
  kind: "page-scrolls-sideways" | "control-out-of-reach" | "scroller-scrolls-sideways";
  detail: string;
}

/** The phone widths checked: iPhone SE / small Android, common Android, Pixel 5. */
export const PHONE_WIDTHS = [320, 360, 393] as const;

/** Runs in the page. Kept free of closures so Playwright can serialise it. */
function collectProblems(): LayoutProblem[] {
  const problems: LayoutProblem[] = [];
  const doc = document.documentElement;
  const vw = doc.clientWidth;
  const SLACK = 1; // sub-pixel rounding

  const describe = (el: Element): string => {
    const cls = typeof (el as HTMLElement).className === "string" ? (el as HTMLElement).className : "";
    const firstClass = cls.trim().split(/\s+/).filter((c) => !c.startsWith("svelte-"))[0];
    const label =
      el.getAttribute("aria-label") ||
      el.getAttribute("title") ||
      (el as HTMLInputElement).placeholder ||
      (el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 30);
    return `<${el.tagName.toLowerCase()}${firstClass ? "." + firstClass : ""}>${label ? ` "${label}"` : ""}`;
  };

  const isShown = (el: Element): boolean => {
    const s = getComputedStyle(el);
    if (s.visibility === "hidden" || s.display === "none") return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };

  const scrollsX = (el: Element) => {
    const s = getComputedStyle(el);
    return (s.overflowX === "auto" || s.overflowX === "scroll") && el.scrollWidth > el.clientWidth + SLACK;
  };
  const scrollsY = (el: Element) => {
    const s = getComputedStyle(el);
    return (s.overflowY === "auto" || s.overflowY === "scroll") && el.scrollHeight > el.clientHeight + SLACK;
  };
  // A deliberate sideways strip: it scrolls horizontally and not vertically.
  const isStrip = (el: Element) => scrollsX(el) && !scrollsY(el);

  if (doc.scrollWidth > vw + SLACK) {
    const culprits: string[] = [];
    for (const el of Array.from(document.body.querySelectorAll("*"))) {
      if (culprits.length >= 3) break;
      if (!isShown(el) || el.getBoundingClientRect().right <= vw + SLACK) continue;
      // Report the outermost offender only, not every descendant of it.
      if (el.parentElement && el.parentElement.getBoundingClientRect().right > vw + SLACK) continue;
      culprits.push(`${describe(el)} reaches ${Math.round(el.getBoundingClientRect().right)}px`);
    }
    problems.push({
      kind: "page-scrolls-sideways",
      detail: `document is ${doc.scrollWidth}px wide in a ${vw}px viewport: ${culprits.join("; ")}`,
    });
  }

  for (const el of Array.from(document.body.querySelectorAll("*"))) {
    if (el === document.body || !isShown(el)) continue;
    if (scrollsX(el) && scrollsY(el)) {
      problems.push({
        kind: "scroller-scrolls-sideways",
        detail: `${describe(el)} scrolls vertically but is also ${el.scrollWidth - el.clientWidth}px too wide`,
      });
    }
  }

  const CONTROLS =
    'a[href], button, input:not([type="hidden"]), select, textarea, summary, [role="button"], ' +
    '[role="tab"], [role="checkbox"], [role="switch"], [role="menuitem"], [role="option"]';
  for (const el of Array.from(document.querySelectorAll(CONTROLS))) {
    if (!isShown(el)) continue;
    // Controls a stylesheet deliberately hid by moving them off-screen (visually-hidden inputs
    // behind a custom toggle, skip links) are 1px or smaller.
    const r = el.getBoundingClientRect();
    if (r.width <= 1 || r.height <= 1) continue;

    let reason: string | null = null;
    let inStrip = false;
    for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
      const s = getComputedStyle(a);
      if (s.overflowX === "visible") continue;
      if (isStrip(a)) {
        inStrip = true;
        continue;
      }
      const ar = a.getBoundingClientRect();
      if (r.right > ar.right + SLACK || r.left < ar.left - SLACK) {
        reason = `clipped by ${describe(a)} (${Math.round(r.left)}-${Math.round(r.right)}px vs ${Math.round(ar.left)}-${Math.round(ar.right)}px)`;
        break;
      }
    }
    if (!reason && !inStrip && (r.right > vw + SLACK || r.left < -SLACK)) {
      reason = `off-screen at ${Math.round(r.left)}-${Math.round(r.right)}px in a ${vw}px viewport`;
    }
    if (reason) problems.push({ kind: "control-out-of-reach", detail: `${describe(el)} ${reason}` });
  }

  return problems;
}

/** Every layout problem on the page as it is rendered right now. */
export function layoutProblems(page: Page): Promise<LayoutProblem[]> {
  return page.evaluate(collectProblems);
}

/** Asserts the current rendering has no layout problems, naming each one found. */
export async function expectCleanLayout(page: Page, where: string): Promise<void> {
  // A list of forty identical rows reports forty identical problems; show each once, counted.
  const counts = new Map<string, number>();
  for (const p of await layoutProblems(page)) {
    const line = `${p.kind}: ${p.detail}`;
    counts.set(line, (counts.get(line) ?? 0) + 1);
  }
  expect(
    [...counts].map(([line, n]) => (n > 1 ? `${line} (x${n})` : line)),
    `layout problems on ${where} at ${page.viewportSize()?.width}px`,
  ).toEqual([]);
}

/** Asserts the element sits entirely inside the visible viewport. */
export async function expectInViewport(page: Page, selectorDescription: string, box: DOMRectLike | null) {
  const vp = page.viewportSize();
  expect(box, `${selectorDescription} has no box`).not.toBeNull();
  if (!box || !vp) return;
  expect(box.x, `${selectorDescription} starts left of the screen`).toBeGreaterThanOrEqual(-1);
  expect(box.y, `${selectorDescription} starts above the screen`).toBeGreaterThanOrEqual(-1);
  expect(box.x + box.width, `${selectorDescription} runs off the right edge`).toBeLessThanOrEqual(vp.width + 1);
  expect(box.y + box.height, `${selectorDescription} runs off the bottom`).toBeLessThanOrEqual(vp.height + 1);
}

export interface DOMRectLike {
  x: number;
  y: number;
  width: number;
  height: number;
}
