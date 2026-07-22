// #294 per-install-type update dialog. Asserts it renders the right thing for each install type:
// a real "Update now" button (native, admin, gate open), an admin-required note (native, readonly),
// the manual command (native, gate closed), and tailored instructions for Docker / HA. Refine
// translate is a key passthrough, so assertions are on the translation keys and the literal commands.
import "@ant-design/v5-patch-for-react-19";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { IInfo } from "../utils/useInfo";
import { UpdateModal } from "./updateModal";

const { infoMock, roleMock, triggerUpdateMock, closeMock } = vi.hoisted(() => ({
  infoMock: vi.fn(),
  roleMock: vi.fn(),
  triggerUpdateMock: vi.fn(),
  closeMock: vi.fn(),
}));

vi.mock("@refinedev/core", () => ({ useTranslate: () => (key: string) => key }));
vi.mock("../utils/useInfo", () => ({ useInfo: () => ({ data: infoMock() }) }));
vi.mock("../utils/auth", () => ({ useCurrentUser: () => ({ data: { role: roleMock() } }) }));
vi.mock("../utils/updateAction", () => ({
  triggerUpdate: triggerUpdateMock,
  // Selector-compatible stub of the zustand store, always "open" so content renders.
  useUpdateModal: (selector: (s: { open: boolean; show: () => void; close: () => void }) => unknown) =>
    selector({ open: true, show: vi.fn(), close: closeMock }),
}));

const info = (overrides: Partial<IInfo>): IInfo => ({ version: "2026.7.14", ...overrides }) as IInfo;

describe("UpdateModal (#294)", () => {
  afterEach(() => {
    infoMock.mockReset();
    roleMock.mockReset();
    triggerUpdateMock.mockReset();
    closeMock.mockReset();
  });

  it("shows a real update button for an admin on a native install and triggers the update", async () => {
    const user = userEvent.setup({ delay: null });
    infoMock.mockReturnValue(
      info({ install_type: "native", update_action_available: true, latest_version: "2026.7.30" }),
    );
    roleMock.mockReturnValue("admin");
    triggerUpdateMock.mockResolvedValue({ status: "started", target: null, restart_managed: true });

    render(<UpdateModal />);

    const button = screen.getByRole("button", { name: "update.action.updateToVersion" });
    await user.click(button);

    await waitFor(() => expect(triggerUpdateMock).toHaveBeenCalledTimes(1));
  });

  it("tells a readonly user an admin is required on a native install", () => {
    infoMock.mockReturnValue(info({ install_type: "native", update_action_available: true }));
    roleMock.mockReturnValue("readonly");

    render(<UpdateModal />);

    expect(screen.getByText("update.action.native.adminRequired")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "update.action.updateNow" })).toBeNull();
    expect(screen.queryByRole("button", { name: "update.action.updateToVersion" })).toBeNull();
  });

  it("shows the manual command when the native action is gated off", () => {
    infoMock.mockReturnValue(info({ install_type: "native", update_action_available: false }));
    roleMock.mockReturnValue("admin");

    render(<UpdateModal />);

    expect(screen.getByText("update.action.native.disabled")).toBeInTheDocument();
    expect(screen.getByText("bash scripts/update.sh")).toBeInTheDocument();
  });

  it("shows the compose pull/up command for a Docker install", () => {
    infoMock.mockReturnValue(info({ install_type: "docker", update_action_available: false }));
    roleMock.mockReturnValue("admin");

    render(<UpdateModal />);

    expect(screen.getByText("update.action.docker.description")).toBeInTheDocument();
    expect(screen.getByText("docker compose pull && docker compose up -d")).toBeInTheDocument();
  });

  it("points a Home Assistant add-on at Supervisor's update UI", () => {
    infoMock.mockReturnValue(info({ install_type: "ha_addon", update_action_available: false }));
    roleMock.mockReturnValue("admin");

    render(<UpdateModal />);

    expect(screen.getByText("update.action.haAddon.steps")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "update.action.updateNow" })).toBeNull();
  });
});
