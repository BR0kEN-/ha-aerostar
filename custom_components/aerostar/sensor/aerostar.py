from typing import AsyncGenerator, ClassVar, Final, Self

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant, callback

from ..aerostar import AerostarVentilationEntity, AerostarVentilationCoordinator
from ..const import (
    ATTR_EXTERNAL_SYSTEM_STATE,
    ATTR_EXTERNAL_SUPPLY_TEMPERATURE,
    ATTR_EXTERNAL_EXHAUST_TEMPERATURE,
    ATTR_EXTERNAL_OUTDOOR_TEMPERATURE,
    ATTR_EXTERNAL_AFTER_RECUP_TEMPERATURE,
    ATTR_EXTERNAL_ELECTRIC_HEATER_1,
    ATTR_EXTERNAL_ELECTRIC_HEATER_2,
    ATTR_EXTERNAL_RECUPERATOR_ICING,
    SYSTEM_STATE_ON,
)


MIN_DELTA_T: Final = 5.0
"""
The minimal extract-to-outdoor temperature difference (K) to compute the
recuperator efficiency at. The worst-case error is `2 * sensor_error / ΔT`,
i.e. ±2% at 5 K for the 0.1 K resolution of the sensors.
"""


ATTR_DESCRIPTION: Final = "description"
ATTR_FORMULA: Final = "formula"
ATTR_UNKNOWN_WHEN: Final = "unknown_when"
ATTR_UNAVAILABLE_WHEN: Final = "unavailable_when"
ATTR_UNKNOWN_REASON: Final = "unknown_reason"

_REASON_SYSTEM_STATE: Final = "system state isn't On: the fans are stopped or the unit is in a special mode"
_REASON_DELTA_T: Final = (
    f"exhaust − outdoor temperature difference is below {MIN_DELTA_T:g} K: too small to measure accurately"
)


def temperature_efficiency(delta: float, max_delta: float) -> float | None:
    """
    :param delta: The temperature change of an airflow across the recuperator.
    :param max_delta: The extract-to-outdoor temperature difference.
    :return: The temperature efficiency (EN 308) in %, clamped to `[0, 100]`.
     The `None` when the temperature difference is too small to be reliable.
    """
    if abs(max_delta) < MIN_DELTA_T:
        return None

    # Signed on purpose: in summer both deltas are negative.
    return round(min(max(delta / max_delta * 100, 0.0), 100.0), 1)


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


class AerostarRecuperatorEfficiencySensor(AerostarVentilationEntity, SensorEntity):
    """
    The supply-side temperature efficiency of the recuperator.
    """

    _attr_icon = "mdi:heat-wave"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    # The static explanations don't need to be stored with every state.
    _unrecorded_attributes = frozenset({
        ATTR_DESCRIPTION,
        ATTR_FORMULA,
        ATTR_UNKNOWN_WHEN,
        ATTR_UNAVAILABLE_WHEN,
    })

    _title: ClassVar[str] = "Recuperator efficiency"
    _description: ClassVar[str] = (
        "How much of the room air heat (or cold in summer) the recuperator passes to the fresh air. "
        "100% means the supply air is as warm as the room air, 0% - as cold as the outdoor air. "
        "The exhaust temperature is the one of the room air entering the unit. "
        "The temperature efficiency per EN 308."
    )
    _formula: ClassVar[str] = "(supply − outdoor) / (exhaust − outdoor) × 100, clamped to 0-100%"
    _unavailable_when: ClassVar[str] = "the supply, exhaust or outdoor temperature is unavailable"
    _delta: ClassVar[tuple[str, str]] = (
        ATTR_EXTERNAL_SUPPLY_TEMPERATURE,
        ATTR_EXTERNAL_OUTDOOR_TEMPERATURE,
    )
    _max_delta: ClassVar[tuple[str, str]] = (
        ATTR_EXTERNAL_EXHAUST_TEMPERATURE,
        ATTR_EXTERNAL_OUTDOOR_TEMPERATURE,
    )
    _distortions: ClassVar[dict[str, str]] = {
        ATTR_EXTERNAL_ELECTRIC_HEATER_1: "electric heater 1 is on: it heats the outdoor air before the recuperator",
        ATTR_EXTERNAL_ELECTRIC_HEATER_2: "electric heater 2 is on: it heats the supply air after the recuperator",
        ATTR_EXTERNAL_RECUPERATOR_ICING: "recuperator anti-icing is active: it boosts exhaust and reduces supply",
    }

    def __init__(self, coordinator: AerostarVentilationCoordinator) -> None:
        super().__init__(self._title, coordinator)

        self._temperatures: Final[frozenset[str]] = frozenset((*self._delta, *self._max_delta))
        self._dependencies: Final[frozenset[str]] = self._temperatures.union(
            (ATTR_EXTERNAL_SYSTEM_STATE, *self._distortions),
        )
        self._attr_extra_state_attributes: Final[dict] = {
            ATTR_DESCRIPTION: self._description,
            ATTR_FORMULA: self._formula,
            ATTR_UNKNOWN_WHEN: [
                _REASON_SYSTEM_STATE,
                *self._distortions.values(),
                _REASON_DELTA_T,
            ],
            ATTR_UNAVAILABLE_WHEN: self._unavailable_when,
            ATTR_UNKNOWN_REASON: None,
        }

    @classmethod
    async def async_setup_entry(
        cls,
        hass: HomeAssistant,
        entry: ConfigEntry[AerostarVentilationCoordinator],
    ) -> AsyncGenerator[Self]:
        variables = entry.runtime_data.config.get("variables", {})

        if all(var_id in variables for var_id in (*cls._delta, *cls._max_delta)):
            yield cls(entry.runtime_data)

    @callback
    def on_update(self, values: dict) -> bool:
        if self._dependencies.isdisjoint(values):
            return False

        data = self.coordinator.data
        attrs = self._attr_extra_state_attributes
        prev = (self._attr_available, self._attr_native_value, attrs[ATTR_UNKNOWN_REASON])
        value = reason = None

        self._attr_available = all(data.get(var_id) is not None for var_id in self._temperatures)

        if self._attr_available:
            reason = self._get_unknown_reason(data)

            if reason is None:
                value = temperature_efficiency(
                    data[self._delta[0]] - data[self._delta[1]],
                    data[self._max_delta[0]] - data[self._max_delta[1]],
                )

                if value is None:
                    reason = _REASON_DELTA_T

        self._attr_native_value = value
        attrs[ATTR_UNKNOWN_REASON] = reason

        return (self._attr_available, self._attr_native_value, attrs[ATTR_UNKNOWN_REASON]) != prev

    def _get_unknown_reason(self, data: dict) -> str | None:
        """
        :return: The reason the value is meaningless: the fans don't run or
         something besides the recuperator affects the temperatures.
        """
        if data.get(ATTR_EXTERNAL_SYSTEM_STATE) != SYSTEM_STATE_ON:
            return _REASON_SYSTEM_STATE

        for var_id, reason in self._distortions.items():
            if data.get(var_id):
                return reason

        return None


class AerostarRecuperatorExhaustEfficiencySensor(AerostarRecuperatorEfficiencySensor):
    """
    The exhaust-side temperature efficiency of the recuperator.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    _title = "Recuperator exhaust efficiency"
    _description = (
        "How much of the room air heat (or cold in summer) stays in the recuperator before the air goes outdoors. "
        "The exhaust temperature is the one of the room air entering the unit, "
        "the after recup temperature - of the air leaving it to the outdoors. "
        "Matches the Recuperator efficiency with balanced airflows and no heat losses. "
        "Recuperator efficiency / this ≈ exhaust airflow / supply airflow: "
        "a big gap means unbalanced fans or heat losses."
    )
    _formula = "(exhaust − after recup) / (exhaust − outdoor) × 100, clamped to 0-100%"
    _unavailable_when = "the exhaust, after recup or outdoor temperature is unavailable"
    _delta = (
        ATTR_EXTERNAL_EXHAUST_TEMPERATURE,
        ATTR_EXTERNAL_AFTER_RECUP_TEMPERATURE,
    )
    # Electric heater 2 is after the recuperator on the supply side.
    _distortions = {
        var_id: reason
        for var_id, reason in AerostarRecuperatorEfficiencySensor._distortions.items()
        if var_id != ATTR_EXTERNAL_ELECTRIC_HEATER_2
    }
