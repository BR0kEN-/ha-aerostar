from ..base import setup
from .aerostar import AerostarVentilationClimate


async_setup_entry = setup(
    (
        AerostarVentilationClimate,
    ),
)
