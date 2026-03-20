"""Custom types for HelGe-biblioteken."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiohttp
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.loader import Integration

    from .api import HelgebibliotekenApiClient
    from .coordinator import HelgebibliotekenDataUpdateCoordinator


type HelgebibliotekenConfigEntry = ConfigEntry[HelgebibliotekenData]


@dataclass
class HelgebibliotekenData:
    """Data for the HelGe-biblioteken integration."""

    client: HelgebibliotekenApiClient
    coordinator: HelgebibliotekenDataUpdateCoordinator
    integration: Integration
    session: aiohttp.ClientSession
