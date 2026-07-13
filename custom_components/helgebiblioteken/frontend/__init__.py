"""JavaScript module registration for the Lovelace cards."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig

from ..const import JSMODULES, URL_BASE  # noqa: TID252

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class JSModuleRegistration:
    """Registers Helgebiblioteken Lovelace cards in Home Assistant."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the registrar."""
        self.hass = hass
        self._registered = False

    async def async_register(self) -> None:
        """Register static path, shell JS, and Lovelace resources."""
        if self._registered:
            return

        await self._async_register_path()
        self._register_extra_js()
        await self._async_register_lovelace_resources()
        self._registered = True

    async def _async_register_path(self) -> None:
        """Register the static HTTP path so card JS files are served."""
        frontend_dir = Path(__file__).parent
        try:
            await self.hass.http.async_register_static_paths(
                [StaticPathConfig(URL_BASE, str(frontend_dir), cache_headers=True)]
            )
            _LOGGER.debug("Registered static path: %s -> %s", URL_BASE, frontend_dir)
        except RuntimeError:
            _LOGGER.debug("Static path already registered: %s", URL_BASE)

    def _register_extra_js(self) -> None:
        """Load card scripts with the shell so Lovelace resolves elements in time."""
        for module in JSMODULES:
            url = f"{URL_BASE}/{module['filename']}?v={module['version']}"
            add_extra_js_url(self.hass, url)
            _LOGGER.debug("Registered extra JS module URL: %s", url)

    async def _async_register_lovelace_resources(self) -> None:
        """Register all card modules as Lovelace resources in storage mode."""
        lovelace = self.hass.data.get("lovelace")
        if not lovelace or lovelace.mode != "storage":
            return

        resources = lovelace.resources
        if hasattr(resources, "async_get_info"):
            await resources.async_get_info()

        existing_resources = [
            resource
            for resource in resources.async_items()
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
                    await resources.async_update_item(
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
            await resources.async_create_item(
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
