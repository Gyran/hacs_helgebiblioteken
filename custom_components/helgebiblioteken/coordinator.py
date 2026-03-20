"""DataUpdateCoordinator for HelGe-biblioteken."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    HelgebibliotekenApiClientAuthenticationError,
    HelgebibliotekenApiClientError,
)

if TYPE_CHECKING:
    from .data import HelgebibliotekenConfigEntry


# https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
class HelgebibliotekenDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    config_entry: HelgebibliotekenConfigEntry

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the coordinator."""
        super().__init__(*args, **kwargs)
        self._last_update_time: datetime | None = None

    async def _async_update_data(self) -> Any:
        """Update data via library."""
        try:
            data = await self.config_entry.runtime_data.client.async_get_data()
        except HelgebibliotekenApiClientAuthenticationError as exception:
            raise ConfigEntryAuthFailed(exception) from exception
        except HelgebibliotekenApiClientError as exception:
            raise UpdateFailed(exception) from exception
        else:
            self._last_update_time = datetime.now(UTC)
            return data

    @property
    def last_update_time(self) -> datetime | None:
        """Return the last successful update time."""
        return self._last_update_time
