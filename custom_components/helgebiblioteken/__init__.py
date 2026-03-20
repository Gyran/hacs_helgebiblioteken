"""
Custom integration to integrate helgebiblioteken with Home Assistant.

For more details about this integration, please refer to
https://github.com/gyran/hacs_helgebiblioteken
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

import aiohttp
from aiohttp.resolver import ThreadedResolver
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.start import async_at_start
from homeassistant.loader import async_get_loaded_integration

from .api import HelgebibliotekenApiClient
from .const import DOMAIN, LOGGER
from .coordinator import HelgebibliotekenDataUpdateCoordinator
from .data import HelgebibliotekenData
from .frontend import JSModuleRegistration

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall

    from .data import HelgebibliotekenConfigEntry

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BUTTON,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    """Set up the Helgebiblioteken integration (frontend only)."""
    # Register static path + extra_js as soon as HA is starting (not only after
    # EVENT_HOMEASSISTANT_STARTED), so index.html includes the card module before
    # the Lovelace card picker loads (otherwise the custom element never appears
    # in time).

    async def _register_frontend(_h: HomeAssistant) -> None:
        await JSModuleRegistration(_h).async_register()

    async_at_start(hass, _register_frontend)
    return True


# https://developers.home-assistant.io/docs/config_entries_index/#setting-up-an-entry
async def async_setup_entry(
    hass: HomeAssistant,
    entry: HelgebibliotekenConfigEntry,
) -> bool:
    """Set up this integration using UI."""
    coordinator = HelgebibliotekenDataUpdateCoordinator(
        hass=hass,
        logger=LOGGER,
        name=DOMAIN,
        update_interval=timedelta(hours=1),
    )
    coordinator.config_entry = entry
    # Use ThreadedResolver to avoid aiodns/pycares compatibility issues.
    connector = aiohttp.TCPConnector(resolver=ThreadedResolver())
    session = aiohttp.ClientSession(connector=connector)
    entry.runtime_data = HelgebibliotekenData(
        client=HelgebibliotekenApiClient(
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
            session=session,
        ),
        integration=async_get_loaded_integration(hass, entry.domain),
        coordinator=coordinator,
        session=session,
    )

    # https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
    await coordinator.async_config_entry_first_refresh()

    # Register refresh service (only once, not per entry)
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    if "_service_registered" not in hass.data[DOMAIN]:

        async def async_refresh_service(call: ServiceCall) -> None:
            """Handle refresh service call."""
            entry_id = call.data.get("entry_id")
            if entry_id:
                # Refresh specific entry
                for config_entry in hass.config_entries.async_entries(DOMAIN):
                    if config_entry.entry_id == entry_id:
                        if hasattr(config_entry, "runtime_data"):
                            LOGGER.info(
                                "Manual refresh requested for %s",
                                config_entry.title,
                            )
                            coord = config_entry.runtime_data.coordinator
                            await coord.async_request_refresh()
                        break
            else:
                # Refresh all entries in parallel
                LOGGER.info("Manual refresh requested for all entries")
                coords = [
                    config_entry.runtime_data.coordinator
                    for config_entry in hass.config_entries.async_entries(DOMAIN)
                    if hasattr(config_entry, "runtime_data")
                ]
                if coords:
                    await asyncio.gather(
                        *(coord.async_request_refresh() for coord in coords)
                    )

        hass.services.async_register(DOMAIN, "refresh", async_refresh_service)
        hass.data[DOMAIN]["_service_registered"] = True

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: HelgebibliotekenConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    await entry.runtime_data.session.close()
    success = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if success:
        remaining = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id
        ]
        if not remaining and hass.data.get(DOMAIN, {}).get("_service_registered"):
            hass.services.async_remove(DOMAIN, "refresh")
            hass.data[DOMAIN]["_service_registered"] = False
            LOGGER.debug("Unregistered refresh service")
    return success


async def async_reload_entry(
    hass: HomeAssistant,
    entry: HelgebibliotekenConfigEntry,
) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
