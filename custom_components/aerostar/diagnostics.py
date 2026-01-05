from typing import Any

from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.redact import async_redact_data

from .aerostar import AerostarVentilationCoordinator


TO_REDACT = (
    CONF_PASSWORD,
)


# noinspection PyUnusedLocal
async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry[AerostarVentilationCoordinator],
) -> dict[str, Any]:
    return {
        "entry": async_redact_data(entry.data, TO_REDACT),
        "data": entry.runtime_data.data,
        "config": entry.runtime_data.config,
    }
