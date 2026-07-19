import { ThemedLayout, ThemedSider, ThemedTitle } from "@refinedev/antd";
import { LinkOutlined } from "@ant-design/icons";
import { useList } from "@refinedev/core";
import { Badge, Menu } from "antd";
import React from "react";
import Logo from "../icon.svg?react";
import { computeLowStock, lowStockNotOnOrderCount } from "../pages/home/analytics";
import { IFilament } from "../pages/filaments/model";
import { parseCustomLinks } from "../utils/customLinks";
import { useGetSetting } from "../utils/querySettings";
import { useLowStockFallbackG } from "../utils/settings";
import { Header } from "./header";

import "./layout.css";

type IconElement = React.ReactElement<{ icon?: React.ReactNode }>;

/**
 * Each item from useMenu/ThemedSider is a <CanAccess> wrapping the real <Menu.Item icon={...}>
 * (see @refinedev/antd's ThemedSider renderTreeView), so the nav badge has to go on that inner
 * element's `icon` prop — CanAccess doesn't forward unknown props to its child.
 */
function withMenuIcon(item: React.ReactNode, icon: React.ReactNode): React.ReactNode {
  if (!React.isValidElement(item)) return item;
  const canAccess = item as React.ReactElement<{ children?: React.ReactNode }>;
  const menuItem = canAccess.props.children;
  if (!React.isValidElement(menuItem)) return item;
  return React.cloneElement(canAccess, {
    children: React.cloneElement(menuItem as IconElement, { icon }),
  });
}

export const SpoolmanLayout = ({ children }: { children: React.ReactNode }) => {
  // User-configured external links (#92), shown as extra nav entries. Absent by default → no change.
  const customLinks = parseCustomLinks(useGetSetting("custom_links").data?.value);

  // Always-visible "Low Stock" nav badge (#298 gate tweak): red count of flagged filaments NOT
  // already on order (no badge at zero — antd Badge hides itself when count is 0). Fetched here
  // (inside <Refine>'s tree, via SpoolmanLayout) rather than in App.tsx, whose `resources` array is
  // built above the Refine/react-query provider and so can't call data hooks itself; react-query
  // dedupes this against the same filament-list query fired by the dashboard/Low Stock page.
  const allFilaments = useList<IFilament>({ resource: "filament", pagination: { mode: "off" } });
  const lowStockFallbackG = useLowStockFallbackG();
  const lowStockBadgeCount = lowStockNotOnOrderCount(
    computeLowStock(allFilaments.result?.data ?? [], lowStockFallbackG),
  );

  return (
    <div className="spoolman-root">
      <ThemedLayout
        Header={() => <Header sticky />}
        Sider={() => (
          <ThemedSider
            fixed
            Title={({ collapsed }) => <ThemedTitle collapsed={collapsed} text="Spoolman" icon={<Logo />} />}
            render={({ items, logout }) => {
              const bottomKeys = ["/settings", "/help"];
              const mainItems: React.ReactNode[] = [];
              const bottomItems: React.ReactNode[] = [];

              React.Children.forEach(items as React.ReactNode, (child) => {
                if (!React.isValidElement(child)) return;
                const key = String(child.key ?? "");
                let withBadge: React.ReactNode = child;
                if (key === "/lowstock") {
                  const menuItem = (child as React.ReactElement<{ children?: IconElement }>).props.children;
                  const baseIcon = React.isValidElement(menuItem) ? menuItem.props.icon : undefined;
                  withBadge = withMenuIcon(
                    child,
                    <Badge count={lowStockBadgeCount} size="small">
                      {baseIcon}
                    </Badge>,
                  );
                }
                if (bottomKeys.some((k) => key.includes(k))) {
                  bottomItems.push(withBadge);
                } else {
                  mainItems.push(withBadge);
                }
              });

              const customLinkItems = customLinks.map((link, index) => (
                <Menu.Item key={`custom-link-${index}`} icon={<LinkOutlined />}>
                  <a href={link.url} target="_blank" rel="noreferrer noopener">
                    {link.name}
                  </a>
                </Menu.Item>
              ));

              return (
                <>
                  {mainItems}
                  {customLinkItems}
                  <li style={{ flex: 1 }} />
                  <Menu.Divider style={{ margin: "0 16px 4px" }} />
                  {bottomItems}
                  {logout}
                </>
              );
            }}
          />
        )}
      >
        {children}
      </ThemedLayout>
    </div>
  );
};
