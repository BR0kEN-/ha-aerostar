from typing import AsyncGenerator, Final, Self

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from ..aerostar import AerostarVentilationEntity, AerostarVentilationCoordinator


class AerostarVentilationAlertSensor(AerostarVentilationEntity, BinarySensorEntity):
    def __init__(
        self,
        coordinator: AerostarVentilationCoordinator,
        sensor: dict,
    ) -> None:
        super().__init__(sensor["name"], coordinator)
        self._attr_device_class: Final[str] = BinarySensorDeviceClass.PROBLEM
        self._attr_extra_state_attributes: Final[dict] = sensor

        if sensor["severity"] == "critical":
            self._attr_icon = "mdi:alert-octagon"
        elif sensor["severity"] == "danger":
            self._attr_icon = "mdi:alert"
        else:
            self._attr_icon = "mdi:alert-circle-outline"

    @classmethod
    async def async_setup_entry(
        cls,
        hass: HomeAssistant,
        entry: ConfigEntry[AerostarVentilationCoordinator],
    ) -> AsyncGenerator[Self]:
        for sensor in entry.runtime_data.alerts:
            yield cls(entry.runtime_data, sensor)

    @callback
    def on_update(self, values: dict) -> None:
        # `None`, `0`, or `1`.
        value = self.coordinator.data.get(self._attr_extra_state_attributes["id"])

        self._attr_is_on = None if value is None else bool(value)
        self._attr_extra_state_attributes["value"] = value
