"""JavaScript module registration for the Lovelace card."""

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from ..const import JSMODULES, URL_BASE  # noqa: TID252

_LOGGER = logging.getLogger(__name__)


class JSModuleRegistration:
    """Registers the Helgebiblioteken Lovelace card in Home Assistant."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the registrar."""
        self.hass = hass

    async def async_register(self) -> None:
        """
        Register static path and inject card JS into the main frontend shell.

        Loading via ``add_extra_js_url`` ensures the custom element is defined
        before the Lovelace card picker opens. Relying only on a Lovelace
        dashboard resource can race the picker's timeout.
        """
        await self._async_register_path()
        self._register_extra_js()

    async def _async_register_path(self) -> None:
        """Register the static HTTP path so the card JS is served."""
        frontend_dir = Path(__file__).parent
        try:
            await self.hass.http.async_register_static_paths(
                [StaticPathConfig(URL_BASE, str(frontend_dir), cache_headers=True)]
            )
            _LOGGER.debug("Registered static path: %s -> %s", URL_BASE, frontend_dir)
        except RuntimeError:
            _LOGGER.debug("Static path already registered: %s", URL_BASE)

    def _register_extra_js(self) -> None:
        """Load card script with the shell so Lovelace resolves the element in time."""
        for module in JSMODULES:
            url = f"{URL_BASE}/{module['filename']}?v={module['version']}"
            add_extra_js_url(self.hass, url)
            _LOGGER.debug("Registered extra JS module URL: %s", url)
