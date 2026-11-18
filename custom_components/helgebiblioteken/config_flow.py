"""Adds config flow for HelGe-biblioteken."""

from __future__ import annotations

import re

import aiohttp
import probatio as vol
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
from .const import DOMAIN, LOGGER, USER_AGENT

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
        _entry_data: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle reauth upon an API authentication error."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Confirm reauthentication with updated credentials."""
        _errors = {}

        reauth_entry = self._get_reauth_entry()

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
                    await self.async_set_unique_id(personnummer)
                    self._abort_if_unique_id_mismatch(reason="wrong_account")
                    return self.async_update_reload_and_abort(
                        reauth_entry,
                        data_updates={
                            CONF_USERNAME: personnummer,
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                        },
                    )

        username_default = reauth_entry.data.get(CONF_USERNAME, vol.UNDEFINED)

        return self.async_show_form(
            step_id="reauth_confirm",
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

    async def _test_credentials(self, username: str, password: str) -> None:
        """Validate credentials."""
        # Use a session with ThreadedResolver to avoid aiodns/pycares
        # compatibility issues (e.g. Channel.getaddrinfo signature mismatch).
        connector = aiohttp.TCPConnector(resolver=ThreadedResolver())
        session = aiohttp.ClientSession(
            connector=connector,
            headers={"User-Agent": USER_AGENT},
        )
        try:
            client = HelgebibliotekenApiClient(
                username=username,
                password=password,
                session=session,
            )
            await client.async_login()
        finally:
            await session.close()
