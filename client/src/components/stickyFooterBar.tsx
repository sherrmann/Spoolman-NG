import { Affix, theme } from "antd";
import { ReactNode } from "react";

const { useToken } = theme;

// The app's scroll container is the antd content pane (`.ant-layout-content` has `overflow: auto`
// in layout.css), NOT the window — the window itself never scrolls. antd Affix tracks `window` by
// default, so without pointing it at the real scroller the bar would never pin. Returning null
// (e.g. in unit tests, where there is no layout) makes Affix fall back to static rendering.
const getScrollContainer = (): HTMLElement | null =>
  typeof document === "undefined" ? null : document.querySelector<HTMLElement>(".ant-layout-content");

/**
 * Pins a create form's action buttons (Save / Save & Add) to the bottom of the scrollable content
 * pane while a long form is scrolled, so they stay reachable without scrolling all the way down
 * (#128). antd Affix only fixes the bar when its natural position is off-screen, so short forms are
 * unaffected.
 */
export function StickyFooterBar({ children }: { children: ReactNode }) {
  const { token } = useToken();
  return (
    <Affix offsetBottom={0} target={getScrollContainer}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: token.marginXS,
          padding: `${token.paddingSM}px 0`,
          background: token.colorBgContainer,
          borderTop: `1px solid ${token.colorBorderSecondary}`,
        }}
      >
        {children}
      </div>
    </Affix>
  );
}
