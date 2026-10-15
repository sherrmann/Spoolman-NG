import { describe, expect, it } from "vitest";
import { defaultConfig, type WizardConfig } from "./model/config";
import { presets } from "./model/presets";
import { configFromSearch, searchFromConfig } from "./urlState";

describe("urlState (#344)", () => {
  it("writes nothing for the defaults and reads an empty query back as the defaults", () => {
    expect(searchFromConfig(defaultConfig)).toBe("");
    expect(configFromSearch("")).toEqual(defaultConfig);
  });

  it("round-trips every preset", () => {
    for (const preset of presets) {
      expect(configFromSearch(`?${searchFromConfig(preset.config)}`)).toEqual(preset.config);
    }
  });

  it("reads the example support link from the issue", () => {
    const config = configFromSearch("?goal=fresh&platform=compose&db=postgres&klipper=1");
    expect(config).toEqual({ ...defaultConfig, database: "postgres", klipper: true });
  });

  it("round-trips every field set away from its default", () => {
    const config: WizardConfig = {
      goal: "switch",
      switchDirection: "docker-to-native",
      platform: "helm",
      klipper: true,
      database: "mysql",
      proxy: "traefik",
      subPath: "/tools/spoolman",
      installedBefore20260719: true,
      extras: {
        nfc: true,
        apiToken: true,
        tz: "America/Argentina/Buenos_Aires",
        puidPgid: { puid: 0, pgid: 1001 },
        ai: true,
        arch: "arm64",
      },
    };
    expect(configFromSearch(searchFromConfig(config))).toEqual(config);
  });

  it("ignores unknown values and keeps the defaults", () => {
    const config = configFromSearch("?goal=nuke&db=oracle&proxy=apache&arch=riscv&klipper=yes&unknown=1");
    expect(config).toEqual(defaultConfig);
  });

  it("refuses free text that could inject into a generated config file", () => {
    const tz = encodeURIComponent("UTC\n    command: rm -rf /");
    const path = encodeURIComponent('/spoolman"; evil');
    const config = configFromSearch(`?tz=${tz}&path=${path}`);
    expect(config.extras.tz).toBeNull();
    expect(config.subPath).toBeNull();
    expect(configFromSearch(`?tz=${"A".repeat(65)}`).extras.tz).toBeNull();
    expect(configFromSearch("?path=/spoolman/../admin").subPath).toBeNull();
    expect(configFromSearch("?tz=-").extras.tz).toBeNull();
    expect(configFromSearch("?tz=1").extras.tz).toBeNull();
  });

  it("keeps an answer typed with surrounding spaces", () => {
    const config = configFromSearch(searchFromConfig({ ...defaultConfig, subPath: "spoolman " }));
    expect(config.subPath).toBe("spoolman");
  });

  it("needs both ids, as plain numbers in range, to set PUID/PGID", () => {
    expect(configFromSearch("?puid=1000").extras.puidPgid).toBeNull();
    expect(configFromSearch("?puid=1000&pgid=-1").extras.puidPgid).toBeNull();
    expect(configFromSearch("?puid=1e3&pgid=1000").extras.puidPgid).toBeNull();
    expect(configFromSearch("?puid=4294967296&pgid=1000").extras.puidPgid).toBeNull();
    expect(configFromSearch("?puid=1000&pgid=100").extras.puidPgid).toEqual({ puid: 1000, pgid: 100 });
  });
});
