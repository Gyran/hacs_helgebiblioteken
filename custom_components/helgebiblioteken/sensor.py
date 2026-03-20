"""Sensor platform for HelGe-biblioteken."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.helpers.entity import EntityCategory

from .entity import HelgebibliotekenEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import HelgebibliotekenDataUpdateCoordinator
    from .data import HelgebibliotekenConfigEntry

LOAN_COUNT_DESCRIPTION = SensorEntityDescription(
    key="helgebiblioteken_loan_count",
    name="Loan Count",
    icon="mdi:book-multiple",
    native_unit_of_measurement="loans",
)

NEXT_EXPIRY_DESCRIPTION = SensorEntityDescription(
    key="helgebiblioteken_next_loan_expiry",
    name="Next Loan Expiry",
    icon="mdi:calendar-clock",
)

LAST_UPDATE_DESCRIPTION = SensorEntityDescription(
    key="helgebiblioteken_last_update",
    name="Last Update",
    icon="mdi:clock-outline",
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001 Unused function argument: `hass`
    entry: HelgebibliotekenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator = entry.runtime_data.coordinator

    async_add_entities(
        [
            LoanCountSensor(
                coordinator=coordinator,
                entity_description=LOAN_COUNT_DESCRIPTION,
            ),
            NextLoanExpirySensor(
                coordinator=coordinator,
                entity_description=NEXT_EXPIRY_DESCRIPTION,
            ),
            LastUpdateSensor(
                coordinator=coordinator,
                entity_description=LAST_UPDATE_DESCRIPTION,
            ),
        ],
    )


class LoanCountSensor(HelgebibliotekenEntity, SensorEntity):
    """Sensor for total loan count with all loans as attributes."""

    def __init__(
        self,
        coordinator: HelgebibliotekenDataUpdateCoordinator,
        entity_description: SensorEntityDescription,
    ) -> None:
        """Initialize the loan count sensor."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{entity_description.key}"
        )

    @property
    def native_value(self) -> int:
        """Return the number of loans."""
        if not self.coordinator.data:
            return 0
        return self.coordinator.data.get("loan_count", 0)

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra state attributes with all loan details."""
        if not self.coordinator.data:
            return {}
        loans = self.coordinator.data.get("loans", [])
        return {
            "loans": loans,
        }


class NextLoanExpirySensor(HelgebibliotekenEntity, SensorEntity):
    """Sensor for the next loan expiry date."""

    _attr_device_class = SensorDeviceClass.DATE

    def __init__(
        self,
        coordinator: HelgebibliotekenDataUpdateCoordinator,
        entity_description: SensorEntityDescription,
    ) -> None:
        """Initialize the next loan expiry sensor."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{entity_description.key}"
        )

    @property
    def native_value(self) -> date | None:
        """Return the next loan expiry date."""
        if not self.coordinator.data:
            return None
        loans = self.coordinator.data.get("loans", [])
        if not loans:
            return None

        # Find the earliest due date
        earliest_date = None

        for loan in loans:
            due_date_str = loan.get("due_date")
            if not due_date_str:
                continue

            try:
                # Parse date (format: YYYY-MM-DD)
                due_date = date.fromisoformat(due_date_str)
                if earliest_date is None or due_date < earliest_date:
                    earliest_date = due_date
            except (ValueError, TypeError):
                # Skip invalid dates
                continue

        return earliest_date

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra state attributes for the next expiring loan."""
        if not self.coordinator.data:
            return {}
        loans = self.coordinator.data.get("loans", [])
        if not loans:
            return {}

        # Find the earliest due date and corresponding loan
        earliest_date = None
        earliest_loan = None

        for loan in loans:
            due_date_str = loan.get("due_date")
            if not due_date_str:
                continue

            try:
                # Parse date (format: YYYY-MM-DD)
                due_date = date.fromisoformat(due_date_str)
                if earliest_date is None or due_date < earliest_date:
                    earliest_date = due_date
                    earliest_loan = loan
            except (ValueError, TypeError):
                continue

        if earliest_loan:
            return {
                "title": earliest_loan.get("title", ""),
                "author": earliest_loan.get("author", ""),
                "due_date": earliest_loan.get("due_date", ""),
                "media_type": earliest_loan.get("media_type", ""),
                "borrowed_from": earliest_loan.get("borrowed_from", ""),
                "can_renew": earliest_loan.get("can_renew", False),
            }
        return {}


class LastUpdateSensor(HelgebibliotekenEntity, SensorEntity):
    """Diagnostic sensor for data last update time."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: HelgebibliotekenDataUpdateCoordinator,
        entity_description: SensorEntityDescription,
    ) -> None:
        """Initialize the last update sensor."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{entity_description.key}"
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the last update time."""
        if not self.coordinator.last_update_success:
            return None
        return self.coordinator.last_update_time
