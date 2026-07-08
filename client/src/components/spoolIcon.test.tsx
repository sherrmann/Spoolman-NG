import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ColorModeContext, ThemePreference } from "../contexts/color-mode";
import SpoolIcon from "./spoolIcon";

// Render SpoolIcon inside a color-mode context so we can assert the #121 dark-mode border fix.
function renderInMode(mode: "light" | "dark", color: Parameters<typeof SpoolIcon>[0]["color"]) {
  return render(
    <ColorModeContext.Provider value={{ mode, preference: mode as ThemePreference, setPreference: () => {} }}>
      <SpoolIcon color={color} />
    </ColorModeContext.Provider>,
  );
}

describe("SpoolIcon dark-mode border (#121)", () => {
  it("applies a light, higher-contrast segment border in dark mode", () => {
    const { container } = renderInMode("dark", "000000");
    const segment = container.querySelector(".spool-icon > div") as HTMLElement;
    expect(segment).toBeTruthy();
    // Inline override wins over the near-invisible CSS default (#44444430).
    expect(segment.style.borderColor).toBe("rgba(255, 255, 255, 0.35)");
    expect(segment.style.backgroundColor).toBe("rgb(0, 0, 0)");
  });

  it("leaves the border to the CSS default in light mode (no inline override)", () => {
    const { container } = renderInMode("light", "000000");
    const segment = container.querySelector(".spool-icon > div") as HTMLElement;
    expect(segment.style.borderColor).toBe("");
  });

  it("also lightens the unknown-color placeholder border in dark mode", () => {
    const { container } = renderInMode("dark", undefined);
    const unknown = container.querySelector(".spool-icon-unknown") as HTMLElement;
    expect(unknown).toBeTruthy();
    expect(unknown.style.borderColor).toBe("rgba(255, 255, 255, 0.35)");
  });

  it("renders one segment per colour for a multi-colour spool", () => {
    const { container } = renderInMode("dark", { colors: ["FF0000", "00FF00", "0000FF"], vertical: false });
    expect(container.querySelectorAll(".spool-icon > div")).toHaveLength(3);
  });
});
