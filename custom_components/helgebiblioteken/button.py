"""Button platform for HelGe-biblioteken."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.helpers.entity import EntityCategory

from .entity import HelgebibliotekenEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import HelgebibliotekenDataUpdateCoordinator
    from .data import HelgebibliotekenConfigEntry

REFRESH_BUTTON_DESCRIPTION = ButtonEntityDescription(
    key="helgebiblioteken_refresh",
    name="Refresh Loans",
    icon="mdi:refresh",
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001 Unused function argument: `hass`
    entry: HelgebibliotekenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the button platform."""
    async_add_entities(
        [
            RefreshButton(
                coordinator=entry.runtime_data.coordinator,
                entity_description=REFRESH_BUTTON_DESCRIPTION,
            ),
        ],
    )


class RefreshButton(HelgebibliotekenEntity, ButtonEntity):
    """Button to refresh loan data."""

    def __init__(
        self,
        coordinator: HelgebibliotekenDataUpdateCoordinator,
        entity_description: ButtonEntityDescription,
    ) -> None:
        """Initialize the refresh button."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{entity_description.key}"
        )

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_request_refresh()
