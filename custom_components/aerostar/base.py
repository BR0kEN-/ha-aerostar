import logging

from abc import ABC
from re import sub
from typing import Any, AsyncGenerator, Callable, ClassVar, Coroutine, Final, Generic, Self, TypeVar

from homeassistant.core import HomeAssistant, callback, is_callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.dispatcher import async_dispatcher_send, async_dispatcher_connect
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity as EntityBase
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from voluptuous import Schema

from .const import DOMAIN, NAME


_AsyncSetupEntry = Callable[[HomeAssistant, ConfigEntry, AddConfigEntryEntitiesCallback], Coroutine[Any, Any, None]]
_Coordinator = TypeVar("_Coordinator", bound="Coordinator")
_DeviceType = TypeVar("_DeviceType", bound="DeviceType")
_Entity = TypeVar("_Entity", bound="Entity")


def idify(value: str) -> str:
    """
    :param value: The input.
    :return: The transformed input.
    """
    return sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def get_generic_args(cls: type, generic_position: int = 0) -> tuple[Any, ...]:
    # The `__orig_bases__` is introduced since 3.7 in PEP-560.
    # See https://peps.python.org/pep-0560/
    #
    # The `[generic_position]` here is the `Generic`
    # that has a `[arg_position]` argument.
    #
    # noinspection PyUnresolvedReferences
    return cls.__orig_bases__[generic_position].__args__


def setup(entity_types: tuple[type[_Entity], ...]) -> _AsyncSetupEntry:
    async def _async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry[_Coordinator],
        async_add_entities: AddConfigEntryEntitiesCallback,
    ) -> None:
        entities: list[_Entity] = []

        for entity_type in entity_types:
            # noinspection PyTypeChecker
            async for child in entity_type.async_setup_entry(hass, entry):
                child.on_update(entry.runtime_data.data)
                entities.append(child)

        async_add_entities(entities, False)

    return _async_setup_entry


class Coordinator(ABC):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry[_Coordinator | None],
    ) -> None:
        self.hass: Final[HomeAssistant] = hass
        self.logger: Final[logging.Logger] = logging.getLogger(entry.data["id"])
        self.config_entry: Final[ConfigEntry[_Coordinator | None]] = entry
        self.data: dict = {}

    async def async_setup(self) -> None:
        raise NotImplementedError

    async def async_unload(self) -> None:
        raise NotImplementedError

    def _signal(self, signal: str, *args: Any) -> None:
        """
        >>> HomeAssistant.verify_event_loop_thread()
        """
        async_dispatcher_send(
            self.hass,
            f"{self.config_entry.data['id']}_{signal}",
            *args,
        )

    def on(self, entity: EntityBase, signal: str) -> None:
        cb = getattr(entity, f"on_{signal}")
        assert is_callback(cb)

        @callback
        def _handler(*args: Any) -> None:
            cb(*args)
            entity.async_write_ha_state()

        entity.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{self.config_entry.data['id']}_{signal}",
                _handler,
            )
        )


class DeviceType(Generic[_Coordinator], ABC):
    type: ClassVar[str]

    def __init__(self, config_schema: Schema) -> None:
        coordinator, = get_generic_args(self.__class__, generic_position=0)
        assert issubclass(coordinator, Coordinator)
        self.coordinator: Final[type[_Coordinator]] = coordinator
        self.config_schema: Final[Schema] = config_schema

    def get_id(self, user_input: dict) -> str:
        """
        :param user_input: The user input from the config flow before the
         config entry creation.
        :return: The value that uniquely identifies the device (e.g. IP, MAC).
         Will be used to produce a unique device ID.
        """
        raise NotImplementedError

    def get_name(self, user_input: dict) -> str:
        """
        :param user_input: The user input from the config flow before the
         config entry creation.
        :return: The value that names the device.
         Will be used to produce a unique device ID.
        """
        raise NotImplementedError


class Entity(Generic[_Coordinator], EntityBase):
    def __init__(self, name: str, coordinator: _Coordinator) -> None:
        self.coordinator: Final[_Coordinator] = coordinator
        self._attr_name: Final[str] = name
        self._attr_has_entity_name: Final[bool] = True
        self._attr_unique_id: Final[str] = f"{coordinator.config_entry.data['id']}_{idify(name)}"
        self._attr_device_info: Final[DeviceInfo] = {
            "name": coordinator.config_entry.title,
            "identifiers": {(DOMAIN, coordinator.config_entry.data['id'])},
            "manufacturer": NAME,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.coordinator.on(self, "update")

    @classmethod
    async def async_setup_entry(
        cls,
        hass: HomeAssistant,
        entry: ConfigEntry[_Coordinator],
    ) -> AsyncGenerator[Self]:
        raise NotImplementedError

    @callback
    def on_update(self, values: dict) -> None:
        raise NotImplementedError


__all__ = [
    "idify",
    "get_generic_args",
    "setup",
    "Coordinator",
    "DeviceType",
    "Entity",
]
