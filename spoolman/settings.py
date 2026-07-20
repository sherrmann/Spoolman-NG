"""Settings that can be changed by the user.

All settings are JSON encoded and stored in the database.
"""

import json
from dataclasses import dataclass
from enum import Enum


class SettingType(Enum):
    """The type of a setting."""

    BOOLEAN = "boolean"
    NUMBER = "number"
    STRING = "string"
    ARRAY = "array"
    OBJECT = "object"


@dataclass
class SettingDefinition:
    """A setting that can be changed by the user."""

    key: str
    type: SettingType
    default: str

    def validate_type(self, value: str) -> None:  # noqa: C901
        """Validate that the value has the correct type."""
        obj = json.loads(value)
        if self.type == SettingType.BOOLEAN:
            if not isinstance(obj, bool):
                raise ValueError(f"Setting {self.key} must be a boolean.")
        elif self.type == SettingType.NUMBER:
            if not isinstance(obj, (int, float)):
                raise ValueError(f"Setting {self.key} must be a number.")
        elif self.type == SettingType.STRING:
            if not isinstance(obj, str):
                raise ValueError(f"Setting {self.key} must be a string.")
        elif self.type == SettingType.ARRAY:
            if not isinstance(obj, list):
                raise ValueError(f"Setting {self.key} must be an array.")
        elif self.type == SettingType.OBJECT:  # noqa: SIM102
            if not isinstance(obj, dict):
                raise ValueError(f"Setting {self.key} must be an object.")


SETTINGS: dict[str, SettingDefinition] = {}


def register_setting(key: str, typ: SettingType, default: str) -> None:
    """Register a setting."""
    SETTINGS[key] = SettingDefinition(key, typ, default)


def parse_setting(key: str) -> SettingDefinition:
    """Parse a setting key."""
    if key not in SETTINGS:
        raise ValueError(f"Setting {key} does not exist.")
    return SETTINGS[key]


register_setting("currency", SettingType.STRING, json.dumps("EUR"))
register_setting("round_prices", SettingType.BOOLEAN, json.dumps(obj=False))
register_setting("print_presets", SettingType.ARRAY, json.dumps([]))
register_setting("print_presets_filament", SettingType.ARRAY, json.dumps([]))
# Default style for the 3D-printable filament swatch download; empty means the
# client-side default style. The known style keys live in the client
# (client/src/utils/swatch/styles.ts), so the backend only stores the string.
register_setting("swatch_style", SettingType.STRING, json.dumps(""))

register_setting("extra_fields_vendor", SettingType.ARRAY, json.dumps([]))
register_setting("extra_fields_filament", SettingType.ARRAY, json.dumps([]))
register_setting("extra_fields_spool", SettingType.ARRAY, json.dumps([]))
register_setting("extra_fields_location", SettingType.ARRAY, json.dumps([]))
register_setting("extra_fields_printer", SettingType.ARRAY, json.dumps([]))
register_setting("base_url", SettingType.STRING, json.dumps(""))

# Custom sidebar links (#92): [{label, url}] shown as extra nav entries.
register_setting("custom_links", SettingType.ARRAY, json.dumps([]))
# Custom per-spool action links (#140): [{name, url_template}] shown as buttons on the spool
# show page and list action menu, with {id} (and other spool fields) substituted.
register_setting("spool_action_links", SettingType.ARRAY, json.dumps([]))

register_setting("locations", SettingType.ARRAY, json.dumps([]))
register_setting("locations_spoolorders", SettingType.OBJECT, json.dumps({}))

# When enabled, large weights/lengths are shown auto-scaled (e.g. 1.5 kg / 64.37 m) instead of raw
# grams/millimeters in the list and detail views (#85). Default off preserves the current display and
# is purely a client-side presentation choice — stored values and the API stay in grams/millimeters.
register_setting("unit_scaling", SettingType.BOOLEAN, json.dumps(obj=False))

# Global fallback low-stock threshold in absolute grams (#298 low-stock redesign). The merged
# per-filament Low Stock view flags a filament with no explicit low_stock_threshold once its aggregate
# remaining weight drops to/below this. Ships at 200 g so Low Stock is truthful out of the box (US5);
# set to 0 to disable the fallback (only explicit thresholds flag).
register_setting("low_stock_fallback_g", SettingType.NUMBER, json.dumps(200))
