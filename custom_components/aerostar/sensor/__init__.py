from ..base import setup
from .aerostar import AerostarSensor


async_setup_entry = setup(
    (
        AerostarSensor,
    ),
)
