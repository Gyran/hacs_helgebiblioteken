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
import probatio as vol
from aiohttp.resolver import ThreadedResolver
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    Platform,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_loaded_integration

from .api import (
    HelgebibliotekenApiClient,
    HelgebibliotekenApiClientError,
    HelgebibliotekenApiClientLoanNotRenewableError,
)
from .const import DOMAIN, LOGGER, USER_AGENT
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
    """Set up the Helgebiblioteken integration: frontend cards and services."""
    await JSModuleRegistration(hass).async_register()
    _async_register_services(hass)
    return True


def _async_register_services(hass: HomeAssistant) -> None:  # noqa: PLR0915
    """Register integration services once, independent of config entries."""

    def _resolve_entry(
        entry_id: str | None, entity_id: str | None = None
    ) -> HelgebibliotekenConfigEntry:
        entries = hass.config_entries.async_loaded_entries(DOMAIN)
        if entry_id:
            for config_entry in entries:
                if config_entry.entry_id == entry_id:
                    return config_entry
            msg = f"Entry '{entry_id}' not found for {DOMAIN}"
            raise ServiceValidationError(msg)

        if entity_id:
            registry = er.async_get(hass)
            registry_entry = registry.async_get(entity_id)
            if registry_entry and registry_entry.config_entry_id:
                for config_entry in entries:
                    if config_entry.entry_id == registry_entry.config_entry_id:
                        return config_entry
            msg = f"Could not resolve config entry from entity '{entity_id}'"
            raise ServiceValidationError(msg)

        if len(entries) == 1:
            return entries[0]

        msg = "Multiple entries configured; provide entry_id or entity_id"
        raise ServiceValidationError(msg)

    async def async_refresh_service(call: ServiceCall) -> None:
        """Handle refresh service call."""
        entry_id = call.data.get("entry_id")
        if entry_id:
            # Refresh specific entry
            for config_entry in hass.config_entries.async_loaded_entries(DOMAIN):
                if config_entry.entry_id == entry_id:
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
                for config_entry in hass.config_entries.async_loaded_entries(DOMAIN)
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
            raise ServiceValidationError(msg)
        try:
            await config_entry.runtime_data.client.async_renew_loan(loan_id)
        except HelgebibliotekenApiClientLoanNotRenewableError as exception:
            raise ServiceValidationError(str(exception)) from exception
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
            result = await config_entry.runtime_data.client.async_renew_due_soon(days)
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
    session = aiohttp.ClientSession(
        connector=connector,
        headers={"User-Agent": USER_AGENT},
    )
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
    try:
        await coordinator.async_config_entry_first_refresh()
    except BaseException:
        await session.close()
        raise

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: HelgebibliotekenConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.session.close()
    return unloaded


async def async_reload_entry(
    hass: HomeAssistant,
    entry: HelgebibliotekenConfigEntry,
) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
