from .base import DeviceType
from .aerostar import AerostarVentilation


DEVICE_TYPES: dict[str, DeviceType] = {
    device.type: device() for device in (
        AerostarVentilation,
    )
}


__all__ = [
    "DEVICE_TYPES",
]
