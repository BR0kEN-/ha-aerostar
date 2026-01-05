import asyncio
import aiohttp

from typing import Final, Generator
from contextlib import suppress

from aiohttp.client_exceptions import ClientConnectorError
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD, UnitOfTemperature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, format_mac
from voluptuous import Required, Schema

from .base import Entity, DeviceType, Coordinator
from .const import (
    ATTR_EXTERNAL_SYSTEM_STATE,
    ATTR_EXTERNAL_SYSTEM_ALARM,
    ATTR_EXTERNAL_SUPPLY_TEMPERATURE,
    ATTR_EXTERNAL_EXHAUST_TEMPERATURE,
    ATTR_EXTERNAL_OUTDOOR_TEMPERATURE,
    ATTR_EXTERNAL_EXHAUST_FAN,
    ATTR_EXTERNAL_SUPPLY_FAN,
    ATTR_EXTERNAL_ELECTRIC_HEATER_1,
    ATTR_EXTERNAL_ELECTRIC_HEATER_2,
    ATTR_EXTERNAL_BYPASS,
)


_LOGIN_API_PATH = "login"
_SUPPORTED_SENSORS = {
    ATTR_EXTERNAL_SYSTEM_STATE: SensorDeviceClass.ENUM,
    ATTR_EXTERNAL_SYSTEM_ALARM: SensorDeviceClass.ENUM,
    ATTR_EXTERNAL_SUPPLY_TEMPERATURE: SensorDeviceClass.TEMPERATURE,
    ATTR_EXTERNAL_EXHAUST_TEMPERATURE: SensorDeviceClass.TEMPERATURE,
    ATTR_EXTERNAL_OUTDOOR_TEMPERATURE: SensorDeviceClass.TEMPERATURE,
    ATTR_EXTERNAL_EXHAUST_FAN: None,
    ATTR_EXTERNAL_SUPPLY_FAN: None,
    ATTR_EXTERNAL_ELECTRIC_HEATER_1: None,
    ATTR_EXTERNAL_ELECTRIC_HEATER_2: None,
    ATTR_EXTERNAL_BYPASS: None,
}


class AerostarVentilationCoordinator(Coordinator):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)

        self._ip: Final[str] = entry.data[CONF_IP_ADDRESS]
        self._password: Final[str] = entry.data[CONF_PASSWORD]
        self._token: str | None = None
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._ws_task: asyncio.Task | None = None

        self.config: dict = {}

    async def async_setup(self) -> None:
        init_attempt = 0

        while True:
            try:
                # Ensure the token to run multiple requests in parallel.
                await self._refresh_token()

                screens, instance, system, self.data = await asyncio.gather(
                    self.async_request("screens"),
                    self.async_request("name"),
                    self.async_request("info"),
                    self.async_request("values"),
                )

                self.config = {
                    **screens,
                    "instance": instance,
                    "system": system,
                }

                for var_id, var_def in self.config["variables"].items():
                    unit = var_def.get("unit")

                    if isinstance(unit, dict):
                        coerced_unit = {}

                        for key, value in unit.items():
                            # Typically the key is a stringified `int` while the status
                            # update comes as an `int` and must be sent like that.
                            coerced_unit[int(key)] = value

                        self.config["variables"][var_id]["unit"] = coerced_unit
                    # Cyrillic `С`.
                    elif unit == "°С":
                        self.config["variables"][var_id]["unit"] = UnitOfTemperature.CELSIUS

                if not self._ws_task or self._ws_task.done():
                    self._ws_task = self.hass.async_create_background_task(
                        self._websocket_listener(),
                        name=self.config_entry.data["id"],
                    )
                break
            except ClientConnectorError as error:
                init_attempt += 1

                if init_attempt > 3:
                    raise error

                await asyncio.sleep(3)

    async def async_unload(self) -> None:
        if self._ws_task:
            self._ws_task.cancel()

            with suppress(asyncio.CancelledError):
                await self._ws_task

        if self._ws and not self._ws.closed:
            await self._ws.close()

    async def async_request(
        self,
        path: str,
        method: str = "GET",
        data: dict | None = None,
        text: bool = False,
    ) -> dict | str:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
        }

        if path != _LOGIN_API_PATH and not self._token:
            await self._refresh_token()

        if self._session is None:
            self._session = async_get_clientsession(self.hass)

        if self._token:
            headers["Authorization"] = self._token

        # noinspection HttpUrlsUsage
        async with self._session.request(
            url=f"http://{self._ip}/api/{path}",
            json=data,
            method=method,
            timeout=10,
            headers=headers
        ) as response:
            if response.status == 401:
                self.logger.warning("token likely expired, retrying")
                self._token = None

                return await self.async_request(path, method, data)

            response.raise_for_status()

            return await (response.text() if text else response.json())

    @property
    def alerts(self) -> Generator[dict, None, None]:
        for var_id, var_def in self.config.get("variables", {}).items():
            severity = var_def.get("alert")

            if severity:
                yield {
                    "id": var_id,
                    "name": var_def.get("name", f"Alarm {var_id}"),
                    "severity": severity,
                }

    @property
    def sensors(self) -> Generator[dict, None, None]:
        for var_id, var_def in self.config.get("variables", {}).items():
            if var_id in _SUPPORTED_SENSORS:
                yield {
                    **var_def,
                    "device_class": _SUPPORTED_SENSORS[var_id],
                }

    async def _refresh_token(self) -> None:
        try:
            result = await self.async_request(
                path=_LOGIN_API_PATH,
                method="POST",
                data={
                    "pass": self._password,
                },
            )

            self._token = result.get("token")
        except Exception as error:
            self.logger.error("login failed: %s", error)
            self._token = None

    def _on_update(self, data: dict) -> None:
        self.data.update(data)
        self._signal("update", data)

    async def _websocket_connect(self) -> None:
        try:
            if not self._token:
                await self._refresh_token()

            self._ws = await self._session.ws_connect(
                f"ws://{self._ip}/ws",
                headers={
                    "Authorization": self._token,
                },
            )
        except Exception as error:
            self.logger.error("WebSocket connection failed: %s", error)
            self._ws = None

    async def _websocket_listener(self) -> None:
        reconnect_delay = 5

        while True:
            try:
                if self._ws is None or self._ws.closed:
                    await self._websocket_connect()

                    if self._ws is None:
                        await asyncio.sleep(reconnect_delay)
                        continue

                async for msg in self._ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            self.hass.loop.call_soon_threadsafe(
                                self._on_update,
                                msg.json(),
                            )
                        except Exception as error:
                            self.logger.error("error processing WebSocket message: %s", error)
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        self.logger.error("WebSocket error: %s", self._ws.exception())
                        break
                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                        self.logger.warning("WebSocket closed")
                        break
            except Exception as error:
                self.logger.error("WebSocket listener error: %s", error)
            finally:
                if self._ws and not self._ws.closed:
                    await self._ws.close()
                self._ws = None
                self.logger.info(f"Reconnecting WebSocket in {reconnect_delay} seconds...")
                await asyncio.sleep(reconnect_delay)


class AerostarVentilationEntity(Entity[AerostarVentilationCoordinator]):
    def __init__(self, name: str, coordinator: AerostarVentilationCoordinator) -> None:
        super().__init__(name, coordinator)

        self._attr_device_info["sw_version"] = coordinator.config["system"].get("version_idf")

        if mac_address := coordinator.config["system"].get("mac"):
            self._attr_device_info["connections"] = {(CONNECTION_NETWORK_MAC, format_mac(mac_address))}


class AerostarVentilation(DeviceType[AerostarVentilationCoordinator]):
    type = "vent"

    def __init__(self) -> None:
        super().__init__(
            config_schema=Schema({
                Required(CONF_IP_ADDRESS): str,
                Required(CONF_PASSWORD): str,
            }),
        )

    def get_id(self, user_input: dict) -> str:
        return user_input[CONF_IP_ADDRESS]


__all__ = [
    "AerostarVentilationCoordinator",
    "AerostarVentilationEntity",
    "AerostarVentilation",
]
