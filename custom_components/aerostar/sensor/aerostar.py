from typing import AsyncGenerator, Final, Self

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from ..aerostar import AerostarVentilationEntity, AerostarVentilationCoordinator


# noinspection Assert
class AerostarSensor(AerostarVentilationEntity, SensorEntity):
    def __init__(
        self,
        coordinator: AerostarVentilationCoordinator,
        sensor: dict,
    ) -> None:
        super().__init__(sensor["name"], coordinator)

        self._attr_device_class: Final[SensorDeviceClass | None] = sensor.get("device_class")
        self._attr_extra_state_attributes: Final[dict] = sensor

        if self._attr_device_class == SensorDeviceClass.ENUM:
            assert isinstance(sensor["unit"], dict)
            self._attr_options: Final[list[str]] = list(sensor["unit"].values())
        else:
            assert isinstance(sensor["unit"], str)
            self._attr_state_class: Final[SensorStateClass] = SensorStateClass.MEASUREMENT
            self._attr_native_unit_of_measurement: Final[str] = sensor["unit"]

    @classmethod
    async def async_setup_entry(
        cls,
        hass: HomeAssistant,
        entry: ConfigEntry[AerostarVentilationCoordinator],
    ) -> AsyncGenerator[Self]:
        for sensor in entry.runtime_data.sensors:
            yield cls(entry.runtime_data, sensor)

    @callback
    def on_update(self, values: dict) -> bool:
        value = self.coordinator.data.get(self._attr_extra_state_attributes["id"])
        prev = self._attr_native_value

        if self._attr_device_class == SensorDeviceClass.ENUM:
            self._attr_native_value = self._attr_extra_state_attributes["unit"].get(value)
        else:
            self._attr_native_value = value

        return self._attr_native_value != prev
