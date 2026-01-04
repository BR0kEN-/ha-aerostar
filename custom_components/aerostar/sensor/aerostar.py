from typing import AsyncGenerator, Final, Self

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from ..aerostar import AerostarVentilationEntity, AerostarVentilationCoordinator


class AerostarSensor(AerostarVentilationEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: AerostarVentilationCoordinator,
        sensor: dict,
    ) -> None:
        super().__init__(sensor["name"], coordinator)

        self._attr_device_class: Final[SensorDeviceClass | None] = sensor.get("device_class")
        self._attr_native_unit_of_measurement: Final[str | None] = sensor.get("unit")
        self._attr_extra_state_attributes: Final[dict] = sensor

    @classmethod
    async def async_setup_entry(
        cls,
        hass: HomeAssistant,
        entry: ConfigEntry[AerostarVentilationCoordinator],
    ) -> AsyncGenerator[Self]:
        for sensor in entry.runtime_data.sensors:
            yield cls(entry.runtime_data, sensor)

    @callback
    def on_update(self, values: dict) -> None:
        self._attr_native_value = self.coordinator.data.get(self._attr_extra_state_attributes["id"])
