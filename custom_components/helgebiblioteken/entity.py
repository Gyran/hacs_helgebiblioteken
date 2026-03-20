"""HelgebibliotekenEntity class."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION
from .coordinator import HelgebibliotekenDataUpdateCoordinator

OBJECT_ID_PREFIX = "Helgebiblioteken "


class HelgebibliotekenEntity(CoordinatorEntity[HelgebibliotekenDataUpdateCoordinator]):
    """HelgebibliotekenEntity class."""

    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: HelgebibliotekenDataUpdateCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.config_entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={
                (
                    coordinator.config_entry.domain,
                    coordinator.config_entry.entry_id,
                ),
            },
            name="Helgebiblioteken",
            manufacturer="Helgebiblioteken",
            model="Library Account",
        )

    @property
    def suggested_object_id(self) -> str | None:
        """Return object_id with prefix so entity_id is e.g. sensor.helgebiblioteken_loan_count."""
        if hasattr(self, "entity_description") and self.entity_description.key:
            return self.entity_description.key

        return super().suggested_object_id  # type: ignore[misc]
