import { Button, Result } from "antd";
import { Component, ErrorInfo, ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { getBasePath } from "../utils/url";

/**
 * Clears the persisted view state most likely to have poisoned a render: the per-table
 * sorters/filters/pagination/showColumns keys, the `savedStates-*` keys, and any
 * hash-encoded view state from a bad shared link. A corrupt value here is the common
 * cause of a white-screened list page (see #44); resetting it lets the app recover.
 */
function clearPersistedViewState(): void {
  try {
    Object.keys(localStorage)
      .filter(
        (k) =>
          k.endsWith("-sorters") ||
          k.endsWith("-filters") ||
          k.endsWith("-pagination") ||
          k.endsWith("-showColumns") ||
          k.startsWith("savedStates-"),
      )
      .forEach((k) => localStorage.removeItem(k));
  } catch {
    /* storage unavailable */
  }
  window.location.hash = "";
}

function ErrorFallback({ onReset }: { onReset: () => void }) {
  const { t } = useTranslation();
  return (
    <Result
      status="error"
      title={t("errorBoundary.title", "Something went wrong")}
      subTitle={t(
        "errorBoundary.subTitle",
        "This page failed to render. If it started after changing or sharing view settings, resetting them usually fixes it.",
      )}
      extra={[
        <Button type="primary" key="reset" onClick={onReset}>
          {t("errorBoundary.reset", "Reset view settings & reload")}
        </Button>,
        <Button key="home" href={getBasePath() + "/"}>
          {t("errorBoundary.home", "Go to home page")}
        </Button>,
      ]}
    />
  );
}

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

/**
 * Top-level error boundary so an unhandled render exception shows a recoverable fallback
 * instead of a blank page. React error boundaries must be class components.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Uncaught render error:", error, info);
  }

  handleReset = (): void => {
    clearPersistedViewState();
    window.location.reload();
  };

  render(): ReactNode {
    if (this.state.hasError) {
      return <ErrorFallback onReset={this.handleReset} />;
    }
    return this.props.children;
  }
}
