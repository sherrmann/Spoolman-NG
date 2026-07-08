import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// Keep tests isolated: unmount React trees and wipe storage between cases so no
// test leaks state (poisoned keys, mounted components) into the next.
//
// This runs last of all afterEach hooks (setupFiles register first; per-file hooks run before it),
// so after cleanup() we drain the macrotask queue. React 19's scheduler flushes unmount/effect work
// through a queued task (setImmediate/MessageChannel); if one is still pending when vitest tears the
// jsdom environment down between files, it fires with no `window` and throws an unhandled
// "window is not defined" — which fails the whole run even though every test passed. Two ticks cover
// a task that reschedules once (e.g. passive-effect cleanup). See TESTING_STRATEGY.md.
afterEach(async () => {
  cleanup();
  localStorage.clear();
  delete (window as Partial<Window>).SPOOLMAN_BASE_PATH;
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
});

// jsdom does not implement matchMedia; antd's responsive hooks (Grid.useBreakpoint)
// call it. Provide an inert stub so components render in the "desktop" branch.
if (!window.matchMedia) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}
