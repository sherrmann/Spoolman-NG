import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StickyFooterBar } from "./stickyFooterBar";

// The bar just wraps a create form's action buttons in an antd Affix so they stay reachable on
// long forms (#128). These smoke tests guard that the children still render and that the wrapper
// carries the themed background/border that separates it from the scrolled content.
describe("StickyFooterBar (#128)", () => {
  it("renders its children (the Save buttons)", () => {
    render(
      <StickyFooterBar>
        <button>Save</button>
        <button>Save &amp; Add</button>
      </StickyFooterBar>,
    );
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save & Add" })).toBeInTheDocument();
  });

  it("wraps the buttons in a flex bar with a top border", () => {
    render(
      <StickyFooterBar>
        <button>Save</button>
      </StickyFooterBar>,
    );
    const bar = screen.getByRole("button", { name: "Save" }).parentElement as HTMLElement;
    expect(bar.style.display).toBe("flex");
    expect(bar.style.borderTop).not.toBe("");
  });
});
