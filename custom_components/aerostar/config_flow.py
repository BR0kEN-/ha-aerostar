from typing import Any

from voluptuous import In, Required, Schema
from homeassistant import config_entries
from homeassistant.const import CONF_DEVICE, CONF_ID, CONF_NAME

from .base import idify
from .const import DOMAIN, NAME
from .device_types import DEVICE_TYPES


UserInput = dict[str, Any] | None


_STEP_SELECT_DEVICE = Schema({
    Required(CONF_NAME): str,
    Required(CONF_DEVICE): In(DEVICE_TYPES.keys()),
})


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: UserInput = None):
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=_STEP_SELECT_DEVICE,
            )

        device_name = user_input[CONF_NAME]
        device_type = user_input[CONF_DEVICE]
        device = DEVICE_TYPES[device_type]

        async def _fn(device_config: UserInput = None):
            if device_config is None:
                return self.async_show_form(
                    step_id=device_type,
                    data_schema=device.config_schema,
                )

            device_id = device.get_id(device_config)

            return self.async_create_entry(
                title=f"{NAME} {device_name}",
                data={
                    **device_config,
                    CONF_DEVICE: device_type,
                    CONF_NAME: device_name,
                    # E.g. `aerostar_vent_ecostar_500_ec_x_192_168_0_33`.
                    CONF_ID: idify(f"{DOMAIN}_{device_type}_{device_name}_{device_id}"),
                },
            )

        setattr(self, f"async_step_{device_type}", _fn)

        return await _fn()
