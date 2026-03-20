"""Adds config flow for HelGe-biblioteken."""

from __future__ import annotations

import re

import aiohttp
import voluptuous as vol
from aiohttp.resolver import ThreadedResolver
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import selector

from .api import (
    HelgebibliotekenApiClient,
    HelgebibliotekenApiClientAuthenticationError,
    HelgebibliotekenApiClientCommunicationError,
    HelgebibliotekenApiClientError,
)
from .const import DOMAIN, LOGGER

# Personnummer format: ÅÅMMDDXXXX (10 digits)
PERSONNUMMER_DIGITS = 10
PERSONNUMMER_DIGITS_WITH_CENTURY = 12


def _normalize_personnummer(value: str) -> str | None:
    """Return 10-digit personnummer (ÅÅMMDDXXXX) if input is valid, else None."""
    digits = re.sub(r"\D", "", value)
    if len(digits) == PERSONNUMMER_DIGITS_WITH_CENTURY:
        digits = digits[2:]  # YYYYMMDDXXXX -> YYMMDDXXXX
    return digits if len(digits) == PERSONNUMMER_DIGITS else None


class HelgebibliotekenFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for HelGe-biblioteken."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle a flow initialized by the user."""
        _errors = {}
        if user_input is not None:
            personnummer = _normalize_personnummer(user_input[CONF_USERNAME])
            if not personnummer:
                _errors["base"] = "invalid_personnummer"
            else:
                try:
                    await self._test_credentials(
                        username=personnummer,
                        password=user_input[CONF_PASSWORD],
                    )
                except HelgebibliotekenApiClientAuthenticationError as exception:
                    LOGGER.warning(exception)
                    _errors["base"] = "auth"
                except HelgebibliotekenApiClientCommunicationError as exception:
                    LOGGER.error(exception)
                    _errors["base"] = "connection"
                except HelgebibliotekenApiClientError as exception:
                    LOGGER.exception(exception)
                    _errors["base"] = "unknown"
                else:
                    await self.async_set_unique_id(unique_id=personnummer)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=personnummer,
                        data={
                            CONF_USERNAME: personnummer,
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=(user_input or {}).get(CONF_USERNAME, vol.UNDEFINED),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="off",
                        ),
                    ),
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                        ),
                    ),
                },
            ),
            errors=_errors,
        )

    async def async_step_reauth(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle reauth upon an API authentication error."""
        _errors = {}

        # Get the entry being reauth'd
        try:
            reauth_entry = self._get_reauth_entry()
        except (ValueError, KeyError):
            # If we can't get the entry yet, return an error
            return self.async_abort(reason="reauth_failed_missing_entry")

        if user_input is not None:
            personnummer = _normalize_personnummer(user_input[CONF_USERNAME])
            if not personnummer:
                _errors["base"] = "invalid_personnummer"
            else:
                try:
                    await self._test_credentials(
                        username=personnummer,
                        password=user_input[CONF_PASSWORD],
                    )
                except HelgebibliotekenApiClientAuthenticationError as exception:
                    LOGGER.warning(exception)
                    _errors["base"] = "auth"
                except HelgebibliotekenApiClientCommunicationError as exception:
                    LOGGER.error(exception)
                    _errors["base"] = "connection"
                except HelgebibliotekenApiClientError as exception:
                    LOGGER.exception(exception)
                    _errors["base"] = "unknown"
                else:
                    self.hass.config_entries.async_update_entry(
                        reauth_entry,
                        data={
                            **reauth_entry.data,
                            CONF_USERNAME: personnummer,
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                        },
                    )
                    await self.hass.config_entries.async_reload(reauth_entry.entry_id)
                    return self.async_abort(reason="reauth_successful")

        # Get username from entry for default value
        username_default = vol.UNDEFINED
        if hasattr(reauth_entry, "data"):
            username_default = reauth_entry.data.get(CONF_USERNAME, vol.UNDEFINED)

        return self.async_show_form(
            step_id="reauth",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=(user_input or {}).get(
                            CONF_USERNAME,
                            username_default,
                        ),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                        ),
                    ),
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                        ),
                    ),
                },
            ),
            errors=_errors,
        )

    def _get_reauth_entry(self) -> config_entries.ConfigEntry:
        """Get the entry being reauth'd."""
        # Try to get entry_id from context
        entry_id = self.context.get("entry_id")
        if entry_id:
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if entry:
                return entry
        # Fallback: try to get from context directly
        if "entry" in self.context:
            return self.context["entry"]
        # Last resort: get from unique_id if available
        if "unique_id" in self.context:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.unique_id == self.context["unique_id"]:
                    return entry
        # If still not found, raise an error
        msg = "Could not find reauth entry"
        raise ValueError(msg)

    async def _test_credentials(self, username: str, password: str) -> None:
        """Validate credentials."""
        # Use a session with ThreadedResolver to avoid aiodns/pycares
        # compatibility issues (e.g. Channel.getaddrinfo signature mismatch).
        connector = aiohttp.TCPConnector(resolver=ThreadedResolver())
        session = aiohttp.ClientSession(connector=connector)
        try:
            client = HelgebibliotekenApiClient(
                username=username,
                password=password,
                session=session,
            )
            await client.async_login()
        finally:
            await session.close()
