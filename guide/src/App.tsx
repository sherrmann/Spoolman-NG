import { useEffect, useMemo, useState } from "react";
import { QuestionForm } from "./components/QuestionForm";
import { PlanView } from "./components/PlanView";
import { type WizardConfig } from "./model/config";
import { buildPlan } from "./model/plan";
import { configFromSearch, searchFromConfig } from "./urlState";

const DOCS_URL = "https://github.com/sherrmann/Spoolman-NG/blob/master/docs/installation.md";
const REPO_URL = "https://github.com/sherrmann/Spoolman-NG";

export default function App() {
  // The answers live in the address bar too, so the page can be shared as a support link (#344).
  const [config, setConfig] = useState<WizardConfig>(() => configFromSearch(window.location.search));
  const plan = useMemo(() => buildPlan(config), [config]);

  useEffect(() => {
    const search = searchFromConfig(config);
    const { pathname, hash } = window.location;
    window.history.replaceState(window.history.state, "", `${pathname}${search ? `?${search}` : ""}${hash}`);
  }, [config]);

  return (
    <div className="app">
      <header className="app-header">
        <h1>Spoolman-NG setup guide</h1>
        <p>
          Answer a few questions and get your exact steps with ready-to-paste config files. The prose reference behind
          every snippet is the <a href={DOCS_URL}>Installation &amp; Configuration guide</a>.
        </p>
      </header>
      <div className="app-columns">
        <aside className="app-form">
          <QuestionForm config={config} onChange={setConfig} />
        </aside>
        <main className="app-plan">
          <h2>Your steps</h2>
          <PlanView plan={plan} />
        </main>
      </div>
      <footer className="app-footer">
        <a href={REPO_URL}>Spoolman-NG on GitHub</a> · generated from the same fragments the docs embed — found a
        mismatch? <a href={`${REPO_URL}/issues`}>File an issue</a>.
      </footer>
    </div>
  );
}
