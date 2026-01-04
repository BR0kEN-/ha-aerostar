from typing import Any

import voluptuous as vol
from homeassistant import config_entries

from .base import idify
from .const import DOMAIN, NAME, ATTR_DEVICE_TYPE
from .device_types import DEVICE_TYPES


UserInput = dict[str, Any] | None


_STEP_SELECT_DEVICE = vol.Schema({
    vol.Required(ATTR_DEVICE_TYPE): vol.In(DEVICE_TYPES.keys()),
})


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: UserInput = None):
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=_STEP_SELECT_DEVICE,
            )

        device_type = user_input[ATTR_DEVICE_TYPE]
        device = DEVICE_TYPES[device_type]

        async def _fn(device_config: UserInput = None):
            if device_config is None:
                return self.async_show_form(
                    step_id=device_type,
                    data_schema=device.config_schema,
                )

            device_id = device.get_id(device_config)
            device_name = device.get_name(device_config)

            return self.async_create_entry(
                title=f"{NAME} {device_name}",
                data={
                    **device_config,
                    "device_type": device_type,
                    # E.g. `aerostar_vent_ecostar_500_ec_x_192_168_0_33`.
                    "id": idify(f"{DOMAIN}_{device_type}_{device_name}_{device_id}"),
                },
            )

        setattr(self, f"async_step_{device_type}", _fn)

        return await _fn()
