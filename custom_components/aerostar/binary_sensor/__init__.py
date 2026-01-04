from ..base import setup
from .aerostar import AerostarVentilationAlertSensor


async_setup_entry = setup(
    (
        AerostarVentilationAlertSensor,
    ),
)
