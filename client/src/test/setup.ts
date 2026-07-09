import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// React 19's scheduler flushes unmount/effect work through a queued task (a MessageChannel, backed by
// setImmediate in this Node/jsdom env — the flake's stack shows Immediate.performWorkUntilDeadline).
// If one is still pending when vitest tears down the jsdom `window` between test files, it fires with
// no `window` and throws an unhandled "ReferenceError: window is not defined". Every test has already
// finished, so it's a benign teardown artifact, but vitest counts ANY uncaughtException as a run
// failure — reddening CI at random even though nothing is wrong. Draining the task queues in afterEach
// (below) makes it rare but can't eliminate it: the task can be (re)scheduled during teardown itself,
// after the drain has run.
//
// So neutralise it deterministically at the source: take over the uncaughtException listeners vitest
// installed at worker startup, swallow EXACTLY this scheduler-after-teardown error, and delegate every
// other uncaught error to the original listeners so real failures still surface. If we somehow ran
// before vitest attached its handler (no prior listeners), rethrow non-benign errors rather than mask
// them. See TESTING_STRATEGY.md.
const isBenignSchedulerTeardownError = (err: unknown): boolean =>
  err instanceof ReferenceError &&
  /window is not defined/.test(err.message) &&
  (err.stack ?? "").includes("performWorkUntilDeadline");

// Reach Node's process/setImmediate through globalThis with local types so this test-only file still
// type-checks under the client build's tsc, which has no @types/node.
type UncaughtListener = (err: unknown, origin: unknown) => void;
interface NodeProcessLike {
  listeners(event: "uncaughtException"): UncaughtListener[];
  removeAllListeners(event: "uncaughtException"): void;
  on(event: "uncaughtException", listener: UncaughtListener): void;
}
const nodeProcess = (globalThis as { process?: NodeProcessLike }).process;
const nodeSetImmediate = (globalThis as { setImmediate?: (callback: () => void) => void }).setImmediate;

if (nodeProcess) {
  const priorUncaughtListeners = nodeProcess.listeners("uncaughtException");
  nodeProcess.removeAllListeners("uncaughtException");
  nodeProcess.on("uncaughtException", (err, origin) => {
    if (isBenignSchedulerTeardownError(err)) {
      return;
    }
    if (priorUncaughtListeners.length === 0) {
      throw err;
    }
    for (const listener of priorUncaughtListeners) {
      listener(err, origin);
    }
  });
}

// Keep tests isolated: unmount React trees and wipe storage between cases so no test leaks state
// (poisoned keys, mounted components) into the next. This runs last of all afterEach hooks (setupFiles
// register first; per-file hooks run before it). Draining the microtask/macrotask/immediate queues
// after cleanup() flushes most of the scheduler's pending work up front so the interceptor above is
// rarely needed; the interceptor is the deterministic backstop for anything scheduled during teardown.
afterEach(async () => {
  cleanup();
  localStorage.clear();
  delete (window as Partial<Window>).SPOOLMAN_BASE_PATH;
  for (let round = 0; round < 2; round++) {
    await Promise.resolve();
    await new Promise((resolve) => setTimeout(resolve, 0));
    if (nodeSetImmediate) {
      await new Promise<void>((resolve) => nodeSetImmediate(() => resolve()));
    }
  }
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
