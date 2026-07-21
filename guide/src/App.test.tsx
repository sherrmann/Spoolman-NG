// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import App from "./App";

afterEach(cleanup);

describe("App (jsdom smoke)", () => {
  it("renders the default plan and reacts to a database change", () => {
    render(<App />);
    expect(screen.getByText("Spoolman-NG setup guide")).toBeTruthy();
    // Default: SQLite quick start — no DB env in the compose artifact.
    expect(document.body.textContent).toContain("docker compose up -d");
    expect(document.body.textContent).not.toContain("SPOOLMAN_DB_TYPE=postgres");

    screen.getByLabelText("PostgreSQL").click();
    expect(document.body.textContent).toContain("SPOOLMAN_DB_TYPE=postgres");
    expect(document.body.textContent).toContain("postgres:16-alpine");
  });

  it("shows the #268 warning when Klipper and an API token are combined", () => {
    render(<App />);
    screen.getByLabelText(/Require an API token/).click();
    expect(document.body.textContent).toContain("SPOOLMAN_API_TOKEN");

    screen.getByLabelText(/Klipper printer\(s\) report/).click();
    expect(document.body.textContent).toContain("API token omitted");
    expect(document.body.textContent).not.toContain("SPOOLMAN_API_TOKEN=");
  });
});
