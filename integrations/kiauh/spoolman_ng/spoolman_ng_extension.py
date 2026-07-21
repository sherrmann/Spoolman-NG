"""KIAUH v6 extension: install/update/remove a native Spoolman NG instance.

Install downloads the latest release zip, runs the bundled installer
(scripts/install.sh, which sets up uv, the venv and the 'Spoolman' systemd
service) and offers to wire Moonraker: the documented [update_manager Spoolman]
zip recipe for one-click updates, the [spoolman] section for filament
tracking, and the moonraker.asvc entry that lets Moonraker restart the
service.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from components.moonraker.services.moonraker_instance_service import (
    MoonrakerInstanceService,
)
from core.instance_manager.instance_manager import InstanceManager
from core.logger import DialogType, Logger
from core.services.backup_service import BackupService
from extensions.base_extension import BaseExtension
from extensions.spoolman_ng import (
    SPOOLMAN_NG_DB_DIR,
    SPOOLMAN_NG_DEFAULT_PORT,
    SPOOLMAN_NG_DIR,
    SPOOLMAN_NG_REPO,
    SPOOLMAN_NG_SERVICE_NAME,
    spoolman_ng,
)
from utils.config_utils import add_config_section, remove_config_section
from utils.fs_utils import run_remove_routines
from utils.input_utils import get_confirm, get_number_input
from utils.sys_utils import get_ipv4_addr, remove_system_service

if TYPE_CHECKING:
    from components.moonraker.moonraker import Moonraker

UPDATE_MANAGER_SECTION = f"update_manager {SPOOLMAN_NG_SERVICE_NAME}"

# The documented Moonraker recipe (docs/installation.md, issue #263). Only
# type:zip reinstalls Python dependencies and restarts the service; .env and
# the local uv/ toolchain are not part of the release zip and must be listed
# in persistent_files to survive updates.
UPDATE_MANAGER_OPTIONS = [
    ("type", "zip"),
    ("channel", "stable"),
    ("repo", SPOOLMAN_NG_REPO),
    ("path", "~/Spoolman"),
    ("virtualenv", ".venv"),
    ("requirements", "requirements.txt"),
    ("persistent_files", [".env", "uv"]),
    ("managed_services", SPOOLMAN_NG_SERVICE_NAME),
]


# noinspection PyMethodMayBeStatic
class SpoolmanNgExtension(BaseExtension):
    def install_extension(self, **kwargs: object) -> None:
        """Install Spoolman NG from the latest release zip and wire Moonraker."""
        Logger.print_status("Installing Spoolman NG ...")

        if spoolman_ng.is_installed():
            Logger.print_info(f"Spoolman NG is already installed in {SPOOLMAN_NG_DIR}.")
            Logger.print_info("Use this extension's update option to update it.")
            return

        Logger.print_dialog(
            DialogType.INFO,
            [
                "Spoolman NG will be installed natively into "
                f"{SPOOLMAN_NG_DIR} from the latest release zip and set up "
                f"as a systemd service named '{SPOOLMAN_NG_SERVICE_NAME}'.",
                "The installer may use sudo to install missing system packages and to register the service.",
            ],
        )
        if not get_confirm("Continue with the installation?", default_choice=True):
            Logger.print_info("Installation aborted.")
            return

        if not spoolman_ng.download_and_extract():
            return

        port: int = SPOOLMAN_NG_DEFAULT_PORT
        if not get_confirm(
            f"Run Spoolman NG on the default port {SPOOLMAN_NG_DEFAULT_PORT}?",
            default_choice=True,
        ):
            port = (
                get_number_input(
                    "Which port should Spoolman NG run on?",
                    min_value=1024,
                    max_value=65535,
                    default=SPOOLMAN_NG_DEFAULT_PORT,
                )
                or SPOOLMAN_NG_DEFAULT_PORT
            )
        spoolman_ng.set_port(port)

        if not spoolman_ng.run_install_script():
            return

        self.__moonraker_integration(port)

        Logger.print_dialog(
            DialogType.SUCCESS,
            [
                "Spoolman NG successfully installed!",
                "You can access Spoolman NG via the following URL:",
                f"http://{get_ipv4_addr()}:{spoolman_ng.get_port()}",
            ],
            center_content=True,
        )

    def update_extension(self, **kwargs: object) -> None:
        """Update the install in place via the bundled scripts/update.sh."""
        Logger.print_status("Updating Spoolman NG ...")

        if not spoolman_ng.is_installed():
            Logger.print_error(f"No Spoolman NG install found in {SPOOLMAN_NG_DIR}.")
            return

        # Installs from before scripts/update.sh existed (< v2026.7.11): overlay
        # the latest release once to obtain it, then --force so the updater
        # still syncs dependencies and restarts the service.
        force = False
        if not spoolman_ng.has_update_script():
            Logger.print_info(
                "This install predates scripts/update.sh — fetching the latest release once to get it ..."
            )
            if not spoolman_ng.download_and_extract():
                return
            force = True

        if not spoolman_ng.run_update_script(force=force):
            return

        Logger.print_dialog(
            DialogType.SUCCESS,
            [
                "Spoolman NG successfully updated!",
                "With the Moonraker integration set up, updates also show up directly in Mainsail/Fluidd.",
            ],
            center_content=True,
        )

    def remove_extension(self, **kwargs: object) -> None:
        """Remove the service, the install dir and the Moonraker integration."""
        Logger.print_status("Removing Spoolman NG ...")

        if not spoolman_ng.is_installed() and not spoolman_ng.service_exists():
            Logger.print_info("Spoolman NG does not seem to be installed. Skipped ...")
            return

        Logger.print_dialog(
            DialogType.WARNING,
            [
                f"This removes the install directory {SPOOLMAN_NG_DIR}, the "
                f"'{SPOOLMAN_NG_SERVICE_NAME}' systemd service and the "
                "Moonraker integration.",
                f"The database in {SPOOLMAN_NG_DB_DIR} is kept unless you explicitly delete it in the last step.",
            ],
        )
        if not get_confirm("Remove Spoolman NG?", default_choice=False):
            Logger.print_info("Removal aborted.")
            return

        mr_instances: list[Moonraker] = self.__get_moonraker_instances()
        if mr_instances:
            Logger.print_status("Removing the Moonraker integration ...")
            BackupService().backup_moonraker_conf()
            remove_config_section(UPDATE_MANAGER_SECTION, mr_instances)
            remove_config_section("spoolman", mr_instances)
            self.__remove_from_moonraker_asvc(mr_instances)
            InstanceManager.restart_all(mr_instances)

        # stop/remove the service before deleting the files it runs from
        if spoolman_ng.service_exists():
            try:
                remove_system_service(f"{SPOOLMAN_NG_SERVICE_NAME}.service")
            except Exception:
                Logger.print_error(
                    "Could not remove the service — leaving the install "
                    "directory in place. Remove the service manually and "
                    "re-run this option."
                )
                return

        if SPOOLMAN_NG_DIR.exists():
            run_remove_routines(SPOOLMAN_NG_DIR)

        if SPOOLMAN_NG_DB_DIR.exists() and get_confirm(
            f"Also delete the database directory {SPOOLMAN_NG_DB_DIR}?",
            default_choice=False,
        ):
            run_remove_routines(SPOOLMAN_NG_DB_DIR)

        Logger.print_dialog(
            DialogType.SUCCESS,
            ["Spoolman NG successfully removed!"],
            center_content=True,
        )

    def __moonraker_integration(self, port: int) -> None:
        Logger.print_dialog(
            DialogType.INFO,
            [
                "Moonraker integration sets up:",
                f"● one-click updates from Mainsail/Fluidd ([{UPDATE_MANAGER_SECTION}])",
                "● Klipper filament tracking ([spoolman] section)",
                f"● '{SPOOLMAN_NG_SERVICE_NAME}' in moonraker.asvc, so Moonraker may restart the service",
            ],
        )
        if not get_confirm("Add the Moonraker integration?", default_choice=True):
            Logger.print_info("Moonraker integration skipped.")
            return

        mr_instances: list[Moonraker] = self.__get_moonraker_instances()
        if not mr_instances:
            Logger.print_warn("No Moonraker instances found. Skipped ...")
            return

        BackupService().backup_moonraker_conf()
        # KIAUH writes options in reverse list order; reverse here so the
        # stanza in moonraker.conf reads exactly like the documented recipe.
        add_config_section(
            section=UPDATE_MANAGER_SECTION,
            instances=mr_instances,
            options=list(reversed(UPDATE_MANAGER_OPTIONS)),
        )
        add_config_section(
            section="spoolman",
            instances=mr_instances,
            options=[("server", f"http://{get_ipv4_addr()}:{port}")],
        )
        self.__add_to_moonraker_asvc(mr_instances)
        InstanceManager.restart_all(mr_instances)
        Logger.print_ok("Moonraker integration configured!")

    def __get_moonraker_instances(self) -> list[Moonraker]:
        mrsvc = MoonrakerInstanceService()
        mrsvc.load_instances()
        return mrsvc.get_all_instances()

    def __add_to_moonraker_asvc(self, instances: list[Moonraker]) -> None:
        for instance in instances:
            asvc = instance.data_dir.joinpath("moonraker.asvc")
            if not asvc.is_file():
                continue
            content = asvc.read_text()
            if SPOOLMAN_NG_SERVICE_NAME in content.splitlines():
                Logger.print_info(f"'{SPOOLMAN_NG_SERVICE_NAME}' already in {asvc}. Skipped ...")
                continue
            if content and not content.endswith("\n"):
                content += "\n"
            asvc.write_text(f"{content}{SPOOLMAN_NG_SERVICE_NAME}\n")
            Logger.print_ok(f"'{SPOOLMAN_NG_SERVICE_NAME}' added to {asvc}!")

    def __remove_from_moonraker_asvc(self, instances: list[Moonraker]) -> None:
        for instance in instances:
            asvc = instance.data_dir.joinpath("moonraker.asvc")
            if not asvc.is_file():
                continue
            lines = asvc.read_text().splitlines()
            if SPOOLMAN_NG_SERVICE_NAME not in lines:
                continue
            kept = [line for line in lines if line != SPOOLMAN_NG_SERVICE_NAME]
            asvc.write_text("\n".join(kept) + "\n" if kept else "")
            Logger.print_ok(f"'{SPOOLMAN_NG_SERVICE_NAME}' removed from {asvc}!")
