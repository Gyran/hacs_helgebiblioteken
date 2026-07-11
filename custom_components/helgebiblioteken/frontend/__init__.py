"""JavaScript module registration for the Lovelace cards."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.helpers.event import async_call_later

from ..const import JSMODULES, URL_BASE  # noqa: TID252

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class JSModuleRegistration:
    """Registers Helgebiblioteken Lovelace cards in Home Assistant."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the registrar."""
        self.hass = hass
        self.lovelace = hass.data.get("lovelace")
        self._path_registered = False
        self._extra_js_registered = False
        self._lovelace_resources_registered = False

    async def async_register(self) -> None:
        """Register static path and inject card JS into the frontend shell."""
        await self._async_register_path()
        self._register_extra_js()

    async def async_register_lovelace_resources(self) -> None:
        """Register all card modules as Lovelace resources in storage mode."""
        if self._lovelace_resources_registered:
            return

        self.lovelace = self.hass.data.get("lovelace")
        if not self.lovelace or self.lovelace.mode != "storage":
            return

        await self._async_wait_for_lovelace_resources()

    async def _async_register_path(self) -> None:
        """Register the static HTTP path so card JS files are served."""
        if self._path_registered:
            return

        frontend_dir = Path(__file__).parent
        try:
            await self.hass.http.async_register_static_paths(
                [StaticPathConfig(URL_BASE, str(frontend_dir), cache_headers=True)]
            )
            self._path_registered = True
            _LOGGER.debug("Registered static path: %s -> %s", URL_BASE, frontend_dir)
        except RuntimeError:
            self._path_registered = True
            _LOGGER.debug("Static path already registered: %s", URL_BASE)

    def _register_extra_js(self) -> None:
        """Load card scripts with the shell so Lovelace resolves elements in time."""
        if self._extra_js_registered:
            return

        for module in JSMODULES:
            url = f"{URL_BASE}/{module['filename']}?v={module['version']}"
            add_extra_js_url(self.hass, url)
            _LOGGER.debug("Registered extra JS module URL: %s", url)

        self._extra_js_registered = True

    async def _async_wait_for_lovelace_resources(self) -> None:
        """Wait until Lovelace resources are loaded, then register all modules."""

        async def _check_loaded(_now: Any) -> None:
            if not self.lovelace or self.lovelace.mode != "storage":
                return

            if not self.lovelace.resources.loaded:
                _LOGGER.debug("Lovelace resources not loaded, retrying in 5s")
                async_call_later(self.hass, 5, _check_loaded)
                return

            await self._async_register_modules()
            self._lovelace_resources_registered = True

        await _check_loaded(None)

    async def _async_register_modules(self) -> None:
        """Register or update every card module as a Lovelace resource."""
        if not self.lovelace:
            return

        existing_resources = [
            resource
            for resource in self.lovelace.resources.async_items()
            if resource["url"].startswith(URL_BASE)
        ]

        for module in JSMODULES:
            url = f"{URL_BASE}/{module['filename']}"
            registered = False

            for resource in existing_resources:
                if self._get_path(resource["url"]) != url:
                    continue

                registered = True
                if self._get_version(resource["url"]) != module["version"]:
                    _LOGGER.info(
                        "Updating %s to version %s",
                        module["name"],
                        module["version"],
                    )
                    await self.lovelace.resources.async_update_item(
                        resource["id"],
                        {
                            "res_type": "module",
                            "url": f"{url}?v={module['version']}",
                        },
                    )
                break

            if registered:
                continue

            _LOGGER.info(
                "Registering %s version %s",
                module["name"],
                module["version"],
            )
            await self.lovelace.resources.async_create_item(
                {
                    "res_type": "module",
                    "url": f"{url}?v={module['version']}",
                }
            )

    @staticmethod
    def _get_path(url: str) -> str:
        """Extract path without query parameters."""
        return url.split("?", maxsplit=1)[0]

    @staticmethod
    def _get_version(url: str) -> str:
        """Extract version query parameter from URL."""
        parts = url.split("?", maxsplit=1)
        if len(parts) > 1 and parts[1].startswith("v="):
            return parts[1].replace("v=", "", 1)
        return "0"
