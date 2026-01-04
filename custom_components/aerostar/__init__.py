from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .base import Coordinator
from .const import ATTR_DEVICE_TYPE
from .device_types import DEVICE_TYPES


PLATFORMS = (
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.SENSOR,
)


# noinspection PyUnusedLocal
async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry[Coordinator]) -> bool:
    entry.runtime_data = DEVICE_TYPES[entry.data[ATTR_DEVICE_TYPE]].coordinator(hass, entry)

    await entry.runtime_data.async_setup()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry[Coordinator]) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry[Coordinator]) -> bool:
    await entry.runtime_data.async_unload()

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
