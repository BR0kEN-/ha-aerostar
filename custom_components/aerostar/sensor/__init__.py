from ..base import setup
from .aerostar import (
    AerostarSensor,
    AerostarRecuperatorEfficiencySensor,
    AerostarRecuperatorExhaustEfficiencySensor,
)


async_setup_entry = setup(
    (
        AerostarSensor,
        AerostarRecuperatorEfficiencySensor,
        AerostarRecuperatorExhaustEfficiencySensor,
    ),
)
