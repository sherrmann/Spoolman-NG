import { Refine } from "@refinedev/core";
import { RefineKbar, RefineKbarProvider } from "@refinedev/kbar";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";

import { ErrorComponent } from "@refinedev/antd";
import "@refinedev/antd/dist/reset.css";

import {
  FileOutlined,
  HighlightOutlined,
  HomeOutlined,
  QuestionOutlined,
  ShoppingCartOutlined,
  TableOutlined,
  ToolOutlined,
  UserOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import loadable, { type DefaultComponent } from "@loadable/component";
import routerBindings, { DocumentTitleHandler, UnsavedChangesNotifier } from "@refinedev/react-router";
import { ConfigProvider } from "antd";
import { Locale } from "antd/es/locale";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { BrowserRouter, Outlet, Route, Routes } from "react-router";
import { ApiTokenModal } from "./components/apiTokenModal";
import dataProvider from "./components/dataProvider";
import { ErrorBoundary } from "./components/errorBoundary";
import { Favicon } from "./components/favicon";
import { SpoolmanLayout } from "./components/layout";
import liveProvider from "./components/liveProvider";
import SpoolmanNotificationProvider from "./components/notificationProvider";
import { ColorModeContextProvider } from "./contexts/color-mode";
import { languages } from "./i18n";
import { getAPIURL, getBasePath } from "./utils/url";

interface ResourcePageProps {
  resource: "spools" | "filaments" | "vendors" | "locations";
  page: "list" | "create" | "edit" | "show";
  mode?: "create" | "clone";
}

// Pages are resolved through an explicit glob rather than `import(`./pages/${...}`)`
// template literals: the bundler emits a chunk for every file a template import could
// reach, which used to ship *.test.tsx — vitest runtime included, ~311 kB — into dist
// and the PWA precache (#170).
const pageModules = import.meta.glob(["./pages/*/*.tsx", "!**/*.test.*"]);

function importPage<Props>(path: string): Promise<DefaultComponent<Props>> {
  const importer = pageModules[path];
  if (!importer) return Promise.reject(new Error(`Unknown page module: ${path}`));
  return importer() as Promise<DefaultComponent<Props>>;
}

const LoadableResourcePage = loadable(
  (props: ResourcePageProps) => importPage<ResourcePageProps>(`./pages/${props.resource}/${props.page}.tsx`),
  {
    fallback: <div>Page is Loading...</div>,
    cacheKey: (props: ResourcePageProps) => `${props.resource}-${props.page}-${props.mode ?? ""}`,
  },
);

interface LoadablePageProps {
  name: string;
}

const LoadablePage = loadable(
  (props: LoadablePageProps) => importPage<LoadablePageProps>(`./pages/${props.name}/index.tsx`),
  {
    fallback: <div>Page is Loading...</div>,
    cacheKey: (props: LoadablePageProps) => `page-${props.name}`,
  },
);

function App() {
  const { t, i18n } = useTranslation();

  const i18nProvider = {
    translate: (key: string, params?: never) => t(key, params),
    changeLocale: (lang: string) => i18n.changeLanguage(lang),
    getLocale: () => i18n.language,
  };

  // Fetch the antd locale using the per-language loader from i18n.ts
  const [antdLocale, setAntdLocale] = useState<Locale | undefined>();
  useEffect(() => {
    const fetchLocale = async () => {
      setAntdLocale(await languages[i18n.language].antd());
    };
    fetchLocale().catch(console.error);
  }, [i18n.language]);

  if (!import.meta.env.VITE_APIURL) {
    return (
      <>
        <h1>Missing API URL</h1>
        <p>
          App was built without an API URL. Please set the VITE_APIURL environment variable to the URL of your Spoolman
          API.
        </p>
      </>
    );
  }

  return (
    <BrowserRouter basename={getBasePath() + "/"}>
      <RefineKbarProvider>
        <ColorModeContextProvider>
          <ConfigProvider locale={antdLocale}>
            <ErrorBoundary>
              <Refine
                dataProvider={dataProvider(getAPIURL())}
                notificationProvider={SpoolmanNotificationProvider}
                i18nProvider={i18nProvider}
                routerProvider={routerBindings}
                liveProvider={liveProvider(getAPIURL())}
                resources={[
                  {
                    name: "home",
                    list: "/",
                    meta: {
                      canDelete: false,
                      icon: <HomeOutlined />,
                    },
                  },
                  {
                    name: "spool",
                    list: "/spool",
                    create: "/spool/create",
                    clone: "/spool/clone/:id",
                    edit: "/spool/edit/:id",
                    show: "/spool/show/:id",
                    meta: {
                      canDelete: true,
                      icon: <FileOutlined />,
                    },
                  },
                  {
                    name: "filament",
                    list: "/filament",
                    create: "/filament/create",
                    clone: "/filament/clone/:id",
                    edit: "/filament/edit/:id",
                    show: "/filament/show/:id",
                    meta: {
                      canDelete: true,
                      icon: <HighlightOutlined />,
                    },
                  },
                  {
                    name: "vendor",
                    list: "/vendor",
                    create: "/vendor/create",
                    clone: "/vendor/clone/:id",
                    edit: "/vendor/edit/:id",
                    show: "/vendor/show/:id",
                    meta: {
                      canDelete: true,
                      icon: <UserOutlined />,
                    },
                  },
                  {
                    name: "locations",
                    list: "/locations",
                    meta: {
                      canDelete: false,
                      icon: <TableOutlined />,
                    },
                  },
                  {
                    // Always visible (US5 amended — supersedes the old conditional-nav rule): the
                    // reorder/shopping destination, and the future home of the #299 purchase links.
                    name: "lowstock",
                    list: "/lowstock",
                    meta: {
                      canDelete: false,
                      label: t("low_stock.title"),
                      // The red "needs attention" count is injected onto this icon by SpoolmanLayout
                      // (components/layout.tsx), which renders inside <Refine> and so can fetch it;
                      // this array is built by App() itself, above the Refine tree.
                      icon: <WarningOutlined />,
                    },
                  },
                  {
                    // Always visible (US5 amended). name "order" maps to the /order API via the
                    // dataProvider (matches useList<IOrder>({ resource: "order" })); its menu entry
                    // links to the /orders page.
                    name: "order",
                    list: "/orders",
                    meta: {
                      canDelete: false,
                      label: t("orders.title"),
                      icon: <ShoppingCartOutlined />,
                    },
                  },
                  {
                    name: "settings",
                    list: "/settings",
                    meta: {
                      canDelete: false,
                      icon: <ToolOutlined />,
                    },
                  },
                  {
                    name: "help",
                    list: "/help",
                    meta: {
                      canDelete: false,
                      icon: <QuestionOutlined />,
                    },
                  },
                ]}
                options={{
                  syncWithLocation: true,
                  warnWhenUnsavedChanges: true,
                  disableTelemetry: true,
                }}
              >
                <Routes>
                  <Route
                    element={
                      <SpoolmanLayout>
                        <Outlet />
                      </SpoolmanLayout>
                    }
                  >
                    <Route index element={<LoadablePage name="home" />} />
                    <Route path="/spool">
                      <Route index element={<LoadableResourcePage resource="spools" page="list" />} />
                      <Route
                        path="create"
                        element={<LoadableResourcePage resource="spools" page="create" mode="create" />}
                      />
                      <Route
                        path="clone/:id"
                        element={<LoadableResourcePage resource="spools" page="create" mode="clone" />}
                      />
                      <Route path="edit/:id" element={<LoadableResourcePage resource="spools" page="edit" />} />
                      <Route path="show/:id" element={<LoadableResourcePage resource="spools" page="show" />} />
                      <Route path="print" element={<LoadablePage name="printing" />} />
                    </Route>
                    <Route path="/filament">
                      <Route index element={<LoadableResourcePage resource="filaments" page="list" />} />
                      <Route
                        path="create"
                        element={<LoadableResourcePage resource="filaments" page="create" mode="create" />}
                      />
                      <Route
                        path="clone/:id"
                        element={<LoadableResourcePage resource="filaments" page="create" mode="clone" />}
                      />
                      <Route path="edit/:id" element={<LoadableResourcePage resource="filaments" page="edit" />} />
                      <Route path="show/:id" element={<LoadableResourcePage resource="filaments" page="show" />} />
                      <Route path="print" element={<LoadablePage name="filamentPrinting" />} />
                    </Route>
                    <Route path="/vendor">
                      <Route index element={<LoadableResourcePage resource="vendors" page="list" />} />
                      <Route
                        path="create"
                        element={<LoadableResourcePage resource="vendors" page="create" mode="create" />}
                      />
                      <Route
                        path="clone/:id"
                        element={<LoadableResourcePage resource="vendors" page="create" mode="clone" />}
                      />
                      <Route path="edit/:id" element={<LoadableResourcePage resource="vendors" page="edit" />} />
                      <Route path="show/:id" element={<LoadableResourcePage resource="vendors" page="show" />} />
                    </Route>
                    <Route path="/settings/*" element={<LoadablePage name="settings" />} />
                    <Route path="/help" element={<LoadablePage name="help" />} />
                    <Route path="/locations" element={<LoadablePage name="locations" />} />
                    <Route path="/lowstock" element={<LoadablePage name="lowstock" />} />
                    <Route path="/orders" element={<LoadablePage name="orders" />} />
                    {/* Location detail (#90): the target a scanned location QR resolves to. */}
                    <Route
                      path="/location/show/:id"
                      element={<LoadableResourcePage resource="locations" page="show" />}
                    />
                    {/* Location label printing (#84). */}
                    <Route path="/location/print" element={<LoadablePage name="locationPrint" />} />
                    <Route path="*" element={<ErrorComponent />} />
                  </Route>
                </Routes>

                <RefineKbar />
                <UnsavedChangesNotifier />
                <DocumentTitleHandler />
                <ReactQueryDevtools />
                <Favicon url={getBasePath() + "/favicon.svg"} />
                <ApiTokenModal />
              </Refine>
            </ErrorBoundary>
          </ConfigProvider>
        </ColorModeContextProvider>
      </RefineKbarProvider>
    </BrowserRouter>
  );
}

export default App;
