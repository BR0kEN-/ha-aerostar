from functools import reduce
from typing import Any, AsyncGenerator, Final, Self

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
    ATTR_HVAC_ACTION,
    ATTR_CURRENT_TEMPERATURE,
    HVACAction,
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
    ATTR_EXTERNAL_SYSTEM_STATE,
    ATTR_EXTERNAL_SUPPLY_TEMPERATURE,
    ATTR_EXTERNAL_TARGET_TEMPERATURE,
    ATTR_EXTERNAL_ELECTRIC_HEATER_1,
    ATTR_EXTERNAL_ELECTRIC_HEATER_2,
    ATTR_EXTERNAL_RECUPERATOR_ICING,
)


ATTR_ENABLED = "enabled"
ATTR_RECUPERATOR_ICING = "recuperator_icing"
ATTR_ELECTRIC_HEATER_1 = "electric_heater1"
ATTR_ELECTRIC_HEATER_2 = "electric_heater2"

FAN_MODES: Final = {
    FAN_AUTO:       0,
    FAN_LOW:        1,
    FAN_MEDIUM:     2,
    FAN_HIGH:       3,
}

HVAC_MODES: Final = {
    # Summer.
    HVACMode.COOL:  0,
    # Winter.
    HVACMode.HEAT:  1,
    # Auto.
    HVACMode.AUTO:  2,
}

HVAC_ACTIONS: Final = {
    # Off.
    HVACAction.OFF:         0,
    # On.
    HVACAction.FAN:         1,
    # Blowing (transitions to from `On`).
    HVACAction.DRYING:      2,
    # Louvers (transitions to from `Off`).
    HVACAction.IDLE:        3,
    # Freecool (unclear when it's active).
    HVACAction.COOLING:     4,
    # Warming (unclear when it's active).
    HVACAction.PREHEATING:  5,
    # Defrost (unclear when it's active).
    HVACAction.DEFROSTING:  6,
}

_ATTRS_VIRTUAL: Final = (
    # Values: `0`, `1`.
    (ATTR_ENABLED,              ATTR_EXTERNAL_ENABLED,              False),
    (ATTR_RECUPERATOR_ICING,    ATTR_EXTERNAL_RECUPERATOR_ICING,    True),
    (ATTR_ELECTRIC_HEATER_1,    ATTR_EXTERNAL_ELECTRIC_HEATER_1,    True),
    (ATTR_ELECTRIC_HEATER_2,    ATTR_EXTERNAL_ELECTRIC_HEATER_2,    True),
)

_ATTRS_EXTERNAL: Final = (
    (ATTR_FAN_MODE,             ATTR_EXTERNAL_FAN_SPEED,            None,                   FAN_MODES),
    (ATTR_HVAC_MODE,            ATTR_EXTERNAL_SEASON,               None,                   HVAC_MODES),
    (ATTR_HVAC_ACTION,          ATTR_EXTERNAL_SYSTEM_STATE,         None,                   HVAC_ACTIONS),
    # Type: `float`.
    (ATTR_TEMPERATURE,          ATTR_EXTERNAL_TARGET_TEMPERATURE,   "target_temperature",   None),
    # Type: `float`.
    (ATTR_CURRENT_TEMPERATURE,  ATTR_EXTERNAL_SUPPLY_TEMPERATURE,   None,                   None),
)


class Attr[_T]:
    def __init__(
        self,
        parent: "AerostarVentilationClimate",
        external_attr: str,
        internal_attr: str,
        options: dict[_T, int] | None = None,
        virtual: bool = False,
        readonly: bool = False,
    ) -> None:
        self._parent: Final["AerostarVentilationClimate"] = parent
        self.external_attr: Final[str] = external_attr
        self.internal_attr: Final[str] = f"_attr_{internal_attr}"
        self.virtual: Final[bool] = virtual
        self.readonly: Final[bool] = readonly

        if options is not None:
            options = {
                "int2ext": options,
                "ext2int": {value: key for key, value in options.items()},
            }

        self.options = options

    @property
    def value(self) -> _T:
        return getattr(self._parent, self.internal_attr, None)

    def set_ha_state(self, value: _T, update_state: bool = False) -> bool:
        prev = self.value
        setattr(self._parent, self.internal_attr, value)

        if update_state:
            self._parent.async_write_ha_state()

        return value != prev

    def set_from_external_state(self, values: dict) -> bool:
        if self.external_attr in values:
            value = values.get(self.external_attr)

            if not self.options:
                return self.set_ha_state(value)

            if value in self.options["ext2int"]:
                return self.set_ha_state(self.options["ext2int"][value])

            self._parent.coordinator.logger.warning(
                (
                    f'{value} of "{self.internal_attr}" cannot be set to "{self.external_attr}"'
                ),
            )

        return False

    async def sync(self, value: _T, *attrs: tuple[Self, Any]) -> None:
        """
        Optimistic set and schedule an external system update.
        """
        try:
            data = {}

            for attr, attr_value in ((self, value), *attrs):
                attr.set_ha_state(attr_value, update_state=not attr.virtual)

                if attr.readonly:
                    self._parent.coordinator.logger.warning(
                        f'{attr_value} of "{attr.external_attr}" is readonly',
                    )
                else:
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
            self._parent.coordinator.logger.warning(
                f"failed to set {self.internal_attr} to {value}: {error}",
            )


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
            **{
                internal_attr: Attr(self, external_attr, internal_attr, virtual=True, readonly=readonly)
                for internal_attr, external_attr, readonly
                in _ATTRS_VIRTUAL
            },
            **{
                internal_attr: Attr(self, external_attr, mapped_to_attr or internal_attr, options=options)
                for internal_attr, external_attr, mapped_to_attr, options
                in _ATTRS_EXTERNAL
            },
        }

    @classmethod
    async def async_setup_entry(
        cls,
        hass: HomeAssistant,
        entry: ConfigEntry[AerostarVentilationCoordinator],
    ) -> AsyncGenerator[Self]:
        yield cls(entry.runtime_data)

    @callback
    def on_update(self, values: dict) -> bool:
        changed = False

        for attr in self._attrs.values():
            if attr.set_from_external_state(values):
                changed = True

        if self._attrs[ATTR_ENABLED].value == 0 and self._attrs[ATTR_HVAC_MODE].set_ha_state(HVACMode.OFF):
            changed = True

        return changed

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

    # The `@property` use is intentional (avoid `@cached_property`).
    @property
    def hvac_action(self) -> HVACAction | None:
        action = super().hvac_action

        # Check if base action is `FAN` to determine special handling requirements.
        # Note: this property is computed on each access (not cached), which is
        # critical - overriding `hvac_action` directly prevents restoration of the
        # base `FAN` state when special conditions end.
        if action == HVACAction.FAN:
            # Anti-icing mode: HRV boosts exhaust and reduces supply to prevent
            # recuperator freezing. Active until temperature rises above ~2°C.
            if self._attrs[ATTR_RECUPERATOR_ICING].value:
                return HVACAction.PREHEATING

            heating_percentage = reduce(
                lambda agg, key: agg + self._attrs[key].value,
                (
                    ATTR_ELECTRIC_HEATER_1,
                    ATTR_ELECTRIC_HEATER_2,
                ),
                0,
            )

            if heating_percentage > 0:
                return HVACAction.HEATING

        return action
