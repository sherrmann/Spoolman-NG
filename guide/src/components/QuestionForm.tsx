import type { Database, Goal, Platform, Proxy, SwitchDirection, WizardConfig } from "../model/config";
import { relevantQuestions } from "../model/config";

interface Props {
  config: WizardConfig;
  onChange: (next: WizardConfig) => void;
}

const GOALS: Array<[Goal, string]> = [
  ["fresh", "Fresh install"],
  ["update", "Update an existing install"],
  ["migrate-upstream", "Migrate from upstream Spoolman"],
  ["switch", "Switch between native and Docker"],
];

const DIRECTIONS: Array<[SwitchDirection, string]> = [
  ["native-to-docker", "Native → Docker"],
  ["docker-to-native", "Docker → Native"],
];

const PLATFORMS: Array<[Platform, string]> = [
  ["compose", "Docker Compose"],
  ["native", "Native Linux (e.g. Raspberry Pi)"],
  ["ha-addon", "Home Assistant add-on"],
  ["helm", "Kubernetes (Helm)"],
  ["third-party-chart", "Third-party chart / NAS catalog"],
];

const DATABASES: Array<[Database, string]> = [
  ["sqlite", "SQLite (default — fine for most homes)"],
  ["postgres", "PostgreSQL"],
  ["mysql", "MySQL / MariaDB"],
];

/** The issue's five proxy choices; "sub-path only" maps to proxy:none + a sub-path. */
type ProxyChoice = Proxy | "subpath-only";

function proxyChoice(config: WizardConfig): ProxyChoice {
  if (config.proxy !== "none") return config.proxy;
  return config.subPath ? "subpath-only" : "none";
}

const PROXIES: Array<[ProxyChoice, string]> = [
  ["none", "None (direct on the LAN)"],
  ["caddy", "Caddy"],
  ["nginx", "nginx"],
  ["traefik", "Traefik"],
  ["subpath-only", "Sub-path behind an existing proxy"],
];

const HELM_EXPOSURE: Array<[ProxyChoice, string]> = [
  ["none", "None (port-forward / in-cluster)"],
  ["nginx", "Ingress (own hostname)"],
  ["subpath-only", "Sub-path behind a shared ingress"],
];

function Radios<T extends string>(props: {
  name: string;
  value: T;
  options: Array<[T, string]>;
  onSelect: (value: T) => void;
}) {
  return (
    <div className="radio-group" role="radiogroup">
      {props.options.map(([value, label]) => (
        <label key={value} className={value === props.value ? "radio selected" : "radio"}>
          <input
            type="radio"
            name={props.name}
            value={value}
            checked={value === props.value}
            onChange={() => props.onSelect(value)}
          />
          {label}
        </label>
      ))}
    </div>
  );
}

export function QuestionForm({ config, onChange }: Props) {
  const relevant = relevantQuestions(config);
  const set = (patch: Partial<WizardConfig>) => onChange({ ...config, ...patch });
  const setExtras = (patch: Partial<WizardConfig["extras"]>) =>
    onChange({ ...config, extras: { ...config.extras, ...patch } });

  const selectProxy = (choice: ProxyChoice) => {
    if (choice === "none") set({ proxy: "none", subPath: null });
    else if (choice === "subpath-only") set({ proxy: "none", subPath: config.subPath ?? "/spoolman" });
    else set({ proxy: choice });
  };

  const platformForUi = config.goal === "switch" ? null : config.platform;
  const showSubPathField = relevant.has("subPath") && proxyChoice(config) !== "none";

  return (
    <form className="question-form" onSubmit={(e) => e.preventDefault()}>
      <fieldset>
        <legend>What are you doing?</legend>
        <Radios name="goal" value={config.goal} options={GOALS} onSelect={(goal) => set({ goal })} />
      </fieldset>

      {relevant.has("switchDirection") && (
        <fieldset>
          <legend>Which direction?</legend>
          <Radios
            name="switchDirection"
            value={config.switchDirection}
            options={DIRECTIONS}
            onSelect={(switchDirection) => set({ switchDirection })}
          />
        </fieldset>
      )}

      {relevant.has("platform") && platformForUi !== null && (
        <fieldset>
          <legend>Where does it run?</legend>
          <Radios
            name="platform"
            value={platformForUi}
            options={PLATFORMS}
            onSelect={(platform) => set({ platform })}
          />
        </fieldset>
      )}

      <fieldset>
        <legend>Klipper</legend>
        <label className="checkbox">
          <input type="checkbox" checked={config.klipper} onChange={(e) => set({ klipper: e.target.checked })} />
          Klipper printer(s) report to this Spoolman via Moonraker
        </label>
      </fieldset>

      {relevant.has("installedBefore20260719") && (
        <fieldset>
          <legend>Install age</legend>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={config.installedBefore20260719}
              onChange={(e) => set({ installedBefore20260719: e.target.checked })}
            />
            This install was set up before 2026-07-19
          </label>
        </fieldset>
      )}

      {relevant.has("database") && (
        <fieldset>
          <legend>Database</legend>
          <Radios
            name="database"
            value={config.database}
            options={DATABASES}
            onSelect={(database) => set({ database })}
          />
        </fieldset>
      )}

      {relevant.has("proxy") && (
        <fieldset>
          <legend>{config.platform === "helm" ? "Exposure" : "Reverse proxy"}</legend>
          <Radios
            name="proxy"
            value={proxyChoice(config)}
            options={config.platform === "helm" ? HELM_EXPOSURE : PROXIES}
            onSelect={selectProxy}
          />
          {showSubPathField && (
            <label className="text-field">
              Sub-path (leave empty for the root)
              <input
                type="text"
                value={config.subPath ?? ""}
                placeholder="/spoolman"
                onChange={(e) => set({ subPath: e.target.value || null })}
              />
            </label>
          )}
        </fieldset>
      )}

      {relevant.has("subPath") && !relevant.has("proxy") && config.platform === "third-party-chart" && (
        <fieldset>
          <legend>Sub-path</legend>
          <label className="text-field">
            Serving under a sub-path? (leave empty for the root)
            <input
              type="text"
              value={config.subPath ?? ""}
              placeholder="/spoolman"
              onChange={(e) => set({ subPath: e.target.value || null })}
            />
          </label>
        </fieldset>
      )}

      {relevant.has("extras") && (
        <fieldset>
          <legend>Extras</legend>
          <label className="checkbox">
            <input type="checkbox" checked={config.extras.nfc} onChange={(e) => setExtras({ nfc: e.target.checked })} />
            Server-side USB NFC reader
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={config.extras.apiToken}
              onChange={(e) => setExtras({ apiToken: e.target.checked })}
            />
            Require an API token
          </label>
          <label className="text-field">
            Timezone (empty = UTC)
            <input
              type="text"
              value={config.extras.tz ?? ""}
              placeholder="Europe/Stockholm"
              onChange={(e) => setExtras({ tz: e.target.value || null })}
            />
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={config.extras.puidPgid !== null}
              onChange={(e) => setExtras({ puidPgid: e.target.checked ? { puid: 1000, pgid: 1000 } : null })}
            />
            Set PUID/PGID (data-volume ownership, Docker only)
          </label>
          {config.extras.puidPgid && (
            <div className="id-fields">
              <label className="text-field">
                PUID
                <input
                  type="number"
                  value={config.extras.puidPgid.puid}
                  onChange={(e) =>
                    setExtras({
                      puidPgid: { puid: Number(e.target.value) || 0, pgid: config.extras.puidPgid?.pgid ?? 1000 },
                    })
                  }
                />
              </label>
              <label className="text-field">
                PGID
                <input
                  type="number"
                  value={config.extras.puidPgid.pgid}
                  onChange={(e) =>
                    setExtras({
                      puidPgid: { puid: config.extras.puidPgid?.puid ?? 1000, pgid: Number(e.target.value) || 0 },
                    })
                  }
                />
              </label>
            </div>
          )}
        </fieldset>
      )}
    </form>
  );
}
