import { ThemedLayout, ThemedSider, ThemedTitle } from "@refinedev/antd";
import { LinkOutlined } from "@ant-design/icons";
import { Menu } from "antd";
import React from "react";
import Logo from "../icon.svg?react";
import { parseCustomLinks } from "../utils/customLinks";
import { useGetSetting } from "../utils/querySettings";
import { Header } from "./header";

import "./layout.css";

export const SpoolmanLayout = ({ children }: { children: React.ReactNode }) => {
  // User-configured external links (#92), shown as extra nav entries. Absent by default → no change.
  const customLinks = parseCustomLinks(useGetSetting("custom_links").data?.value);

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
                if (bottomKeys.some((k) => key.includes(k))) {
                  bottomItems.push(child);
                } else {
                  mainItems.push(child);
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
