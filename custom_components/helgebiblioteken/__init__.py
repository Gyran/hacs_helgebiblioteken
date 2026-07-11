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
import voluptuous as vol
from aiohttp.resolver import ThreadedResolver
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import CoreState
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.start import async_at_start
from homeassistant.loader import async_get_loaded_integration

from .api import HelgebibliotekenApiClient, HelgebibliotekenApiClientError
from .const import DOMAIN, LOGGER
from .coordinator import HelgebibliotekenDataUpdateCoordinator
from .data import HelgebibliotekenData
from .frontend import JSModuleRegistration

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall

    from .data import HelgebibliotekenConfigEntry

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
RENEW_LOAN_SCHEMA = vol.Schema(
    {
        vol.Required("loan_id"): cv.string,
        vol.Optional("entry_id"): cv.string,
        vol.Optional("entity_id"): cv.string,
    }
)
RENEW_DUE_SOON_SCHEMA = vol.Schema(
    {
        vol.Optional("days", default=3): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=30)
        ),
        vol.Optional("entry_id"): cv.string,
        vol.Optional("entity_id"): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    """Set up the Helgebiblioteken integration (frontend only)."""
    frontend = JSModuleRegistration(hass)

    async def _register_frontend_shell(_h: HomeAssistant) -> None:
        # Load card scripts early so the Lovelace picker can resolve custom elements.
        await frontend.async_register()

    async def _register_lovelace_resources(_event=None) -> None:
        await frontend.async_register_lovelace_resources()

    async_at_start(hass, _register_frontend_shell)

    if hass.state == CoreState.running:
        await _register_lovelace_resources()
    else:
        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED, _register_lovelace_resources
        )

    return True


# https://developers.home-assistant.io/docs/config_entries_index/#setting-up-an-entry
async def async_setup_entry(  # noqa: PLR0915
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

        def _resolve_entry(
            entry_id: str | None, entity_id: str | None = None
        ) -> HelgebibliotekenConfigEntry:
            entries = [
                config_entry
                for config_entry in hass.config_entries.async_entries(DOMAIN)
                if hasattr(config_entry, "runtime_data")
            ]
            if entry_id:
                for config_entry in entries:
                    if config_entry.entry_id == entry_id:
                        return config_entry
                msg = f"Entry '{entry_id}' not found for {DOMAIN}"
                raise HomeAssistantError(msg)

            if entity_id:
                registry = er.async_get(hass)
                registry_entry = registry.async_get(entity_id)
                if registry_entry and registry_entry.config_entry_id:
                    for config_entry in entries:
                        if config_entry.entry_id == registry_entry.config_entry_id:
                            return config_entry
                msg = f"Could not resolve config entry from entity '{entity_id}'"
                raise HomeAssistantError(msg)

            if len(entries) == 1:
                return entries[0]

            msg = "Multiple entries configured; provide entry_id or entity_id"
            raise HomeAssistantError(msg)

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

        async def async_renew_loan_service(call: ServiceCall) -> None:
            """Handle renew loan service call."""
            config_entry = _resolve_entry(
                call.data.get("entry_id"), call.data.get("entity_id")
            )
            loan_id = str(call.data["loan_id"]).strip()
            if not loan_id:
                msg = "loan_id cannot be empty"
                raise HomeAssistantError(msg)
            try:
                await config_entry.runtime_data.client.async_renew_loan(loan_id)
            except HelgebibliotekenApiClientError as exception:
                raise HomeAssistantError(str(exception)) from exception
            await config_entry.runtime_data.coordinator.async_request_refresh()

        async def async_renew_due_soon_service(call: ServiceCall) -> None:
            """Handle renew due soon service call."""
            config_entry = _resolve_entry(
                call.data.get("entry_id"), call.data.get("entity_id")
            )
            days = int(call.data["days"])
            try:
                result = await config_entry.runtime_data.client.async_renew_due_soon(
                    days
                )
            except HelgebibliotekenApiClientError as exception:
                raise HomeAssistantError(str(exception)) from exception
            if result["renewed"] or result["failed"]:
                await config_entry.runtime_data.coordinator.async_request_refresh()

        hass.services.async_register(DOMAIN, "refresh", async_refresh_service)
        hass.services.async_register(
            DOMAIN,
            "renew_loan",
            async_renew_loan_service,
            schema=RENEW_LOAN_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            "renew_due_soon",
            async_renew_due_soon_service,
            schema=RENEW_DUE_SOON_SCHEMA,
        )
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
            hass.services.async_remove(DOMAIN, "renew_loan")
            hass.services.async_remove(DOMAIN, "renew_due_soon")
            hass.data[DOMAIN]["_service_registered"] = False
            LOGGER.debug("Unregistered refresh service")
    return success


async def async_reload_entry(
    hass: HomeAssistant,
    entry: HelgebibliotekenConfigEntry,
) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
