from typing import Any, AsyncGenerator, Final, Literal, Self

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    FAN_AUTO,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_HIGH,
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ATTR_CURRENT_TEMPERATURE,
    HVACMode,
    ClimateEntityFeature,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    UnitOfTemperature,
)

from ..aerostar import AerostarVentilationEntity, AerostarVentilationCoordinator
from ..const import (
    ATTR_EXTERNAL_SEASON,
    ATTR_EXTERNAL_ENABLED,
    ATTR_EXTERNAL_FAN_SPEED,
    ATTR_EXTERNAL_SUPPLY_TEMPERATURE,
    ATTR_EXTERNAL_TARGET_TEMPERATURE,
)


ATTR_ENABLED = "enabled"


class Attr[_T]:
    def __init__(
        self,
        parent: "AerostarVentilationClimate",
        external_attr: str,
        internal_attr: str,
        options: dict[_T, int] | None = None,
        virtual: bool = False,
    ) -> None:
        self._parent: Final["AerostarVentilationClimate"] = parent
        self.external_attr: Final[str] = external_attr
        self.internal_attr: Final[str] = internal_attr
        self.virtual: Final[bool] = virtual

        self.set_ha_state(parent.coordinator.data.get(external_attr))

        if options is not None:
            options = {
                "int2ext": options,
                "ext2int": {value: key for key, value in options.items()},
            }

        self.options = options

    @property
    def value(self) -> _T:
        return getattr(self._parent, self.internal_attr)

    def set_ha_state(self, value: _T, update_state: bool = False) -> None:
        setattr(self._parent, self.internal_attr, value)

        if update_state:
            self._parent.async_write_ha_state()

    def set_from_external_state(self, values: dict) -> None:
        if self.external_attr in values:
            value = values.get(self.external_attr)

            self.set_ha_state(
                self.options["ext2int"].get(value, self.value)
                if self.options
                else value
            )

    async def sync(self, value: _T, *attrs: tuple[Self, Any]) -> None:
        """
        Optimistic set and schedule an external system update.
        """
        try:
            data = {}

            for attr, attr_value in ((self, value), *attrs):
                attr.set_ha_state(attr_value, update_state=not attr.virtual)

                data[attr.external_attr] = (
                    attr.options["int2ext"].get(attr_value)
                    if attr.options
                    else attr_value
                )

            result = await self._parent.coordinator.async_request(
                path="values",
                method="POST",
                data=data,
                text=True,
            )

            # NOTE: passing wrong `value` also returns `OK`.
            # Nice design! TBH, IDK when it's non-`OK`.
            if result != "OK":
                raise RuntimeError(result)
        except Exception as error:
            self._parent.coordinator.logger.warning(f"failed to set {self.internal_attr} to {value}: {error}")


class AerostarVentilationClimate(AerostarVentilationEntity, ClimateEntity):
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE

    _attr_hvac_modes = [
        HVACMode.OFF,
        HVACMode.HEAT,
        HVACMode.COOL,
        HVACMode.AUTO,
    ]

    _attr_fan_modes = [
        FAN_AUTO,
        FAN_LOW,
        FAN_MEDIUM,
        FAN_HIGH,
    ]

    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: AerostarVentilationCoordinator) -> None:
        super().__init__(coordinator.config["instance"]["Name"], coordinator)
        self._attr_icon = "mdi:air-filter"
        self._attr_min_temp = coordinator.config["variables"][ATTR_EXTERNAL_TARGET_TEMPERATURE]["control"]["min"]
        self._attr_max_temp = coordinator.config["variables"][ATTR_EXTERNAL_TARGET_TEMPERATURE]["control"]["max"]
        self._attrs = {
            ATTR_ENABLED: Attr[Literal[1, 0]](
                parent=self,
                external_attr=ATTR_EXTERNAL_ENABLED,
                internal_attr="_attr_enabled",
                virtual=True,
            ),
            ATTR_FAN_MODE: Attr[str](
                parent=self,
                external_attr=ATTR_EXTERNAL_FAN_SPEED,
                internal_attr="_attr_fan_mode",
                options={
                    FAN_AUTO: 0,
                    FAN_LOW: 1,
                    FAN_MEDIUM: 2,
                    FAN_HIGH: 3,
                },
            ),
            ATTR_HVAC_MODE: Attr[str](
                parent=self,
                external_attr=ATTR_EXTERNAL_SEASON,
                internal_attr="_attr_hvac_mode",
                options={
                    # Summer.
                    HVACMode.COOL: 0,
                    # Winter.
                    HVACMode.HEAT: 1,
                    # Auto.
                    HVACMode.AUTO: 2,
                },
            ),
            ATTR_TEMPERATURE: Attr[float](
                parent=self,
                external_attr=ATTR_EXTERNAL_TARGET_TEMPERATURE,
                internal_attr="_attr_target_temperature",
            ),
            ATTR_CURRENT_TEMPERATURE: Attr[float](
                parent=self,
                external_attr=ATTR_EXTERNAL_SUPPLY_TEMPERATURE,
                internal_attr="_attr_current_temperature",
            ),
        }

    @classmethod
    async def async_setup_entry(
        cls,
        hass: HomeAssistant,
        entry: ConfigEntry[AerostarVentilationCoordinator],
    ) -> AsyncGenerator[Self]:
        yield cls(entry.runtime_data)

    @callback
    def on_update(self, values: dict) -> None:
        for attr in self._attrs.values():
            attr.set_from_external_state(values)

        if self._attrs[ATTR_ENABLED].value == 0:
            self._attrs[ATTR_HVAC_MODE].set_ha_state(HVACMode.OFF)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is None:
            return

        await self._attrs[ATTR_TEMPERATURE].sync(temp)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self._attrs[ATTR_FAN_MODE].sync(fan_mode)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        # Setting to OFF.
        if hvac_mode == HVACMode.OFF:
            # Setting only HA state because the Aerostar doesn't have such control.
            self._attrs[ATTR_HVAC_MODE].set_ha_state(hvac_mode, update_state=True)
            # In Aerostar that's a separate param rather than an OFF mode.
            await self._attrs[ATTR_ENABLED].sync(0)
        # Setting to any non-OFF mode.
        else:
            # Marked as disabled?
            if self._attrs[ATTR_ENABLED].value == 0:
                # Supply a mode and enable.
                await self._attrs[ATTR_HVAC_MODE].sync(hvac_mode, (self._attrs[ATTR_ENABLED], 1))
            else:
                await self._attrs[ATTR_HVAC_MODE].sync(hvac_mode)
