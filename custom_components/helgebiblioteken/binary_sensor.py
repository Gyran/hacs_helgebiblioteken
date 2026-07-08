"""Binary sensor platform for HelGe-biblioteken."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.util import dt as dt_util

from .entity import HelgebibliotekenEntity
from .reservation import is_reservation_ready_for_pickup

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import HelgebibliotekenDataUpdateCoordinator
    from .data import HelgebibliotekenConfigEntry

# Number of days before the due date a loan is considered "due soon".
DUE_SOON_DAYS = 3

OVERDUE_DESCRIPTION = BinarySensorEntityDescription(
    key="helgebiblioteken_loans_overdue",
    name="Loans Overdue",
    icon="mdi:book-alert",
    device_class=BinarySensorDeviceClass.PROBLEM,
)

DUE_SOON_DESCRIPTION = BinarySensorEntityDescription(
    key="helgebiblioteken_loans_due_soon",
    name="Loans Due Soon",
    icon="mdi:book-clock",
    device_class=BinarySensorDeviceClass.PROBLEM,
)

RESERVATIONS_READY_DESCRIPTION = BinarySensorEntityDescription(
    key="helgebiblioteken_reservations_ready_for_pickup",
    name="Reservations Ready for Pickup",
    icon="mdi:book-check",
    device_class=BinarySensorDeviceClass.PROBLEM,
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001 Unused function argument: `hass`
    entry: HelgebibliotekenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    coordinator = entry.runtime_data.coordinator

    async_add_entities(
        [
            OverdueLoansBinarySensor(
                coordinator=coordinator,
                entity_description=OVERDUE_DESCRIPTION,
            ),
            DueSoonLoansBinarySensor(
                coordinator=coordinator,
                entity_description=DUE_SOON_DESCRIPTION,
            ),
            ReservationsReadyForPickupBinarySensor(
                coordinator=coordinator,
                entity_description=RESERVATIONS_READY_DESCRIPTION,
            ),
        ],
    )


def _parse_due_date(loan: dict) -> date | None:
    """Return the loan due date as a date, or None if missing/invalid."""
    due_date_str = loan.get("due_date")
    if not due_date_str:
        return None
    try:
        return date.fromisoformat(due_date_str)
    except ValueError, TypeError:
        return None


class _LoanDueBinarySensor(HelgebibliotekenEntity, BinarySensorEntity):
    """Base class for loan due-date binary sensors."""

    def __init__(
        self,
        coordinator: HelgebibliotekenDataUpdateCoordinator,
        entity_description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{entity_description.key}"
        )

    def _matching_loans(self, today: date) -> list[dict]:
        """Return the loans that match this sensor's condition."""
        raise NotImplementedError

    @property
    def is_on(self) -> bool:
        """Return True if any loan matches the condition."""
        if not self.coordinator.data:
            return False
        today = dt_util.now().date()
        return bool(self._matching_loans(today))

    @property
    def extra_state_attributes(self) -> dict:
        """Return count and details of the matching loans."""
        if not self.coordinator.data:
            return {"count": 0, "loans": []}
        today = dt_util.now().date()
        matching = self._matching_loans(today)
        return {
            "count": len(matching),
            "loans": [
                {
                    "title": loan.get("title", ""),
                    "author": loan.get("author", ""),
                    "due_date": loan.get("due_date", ""),
                    "media_type": loan.get("media_type", ""),
                    "borrowed_from": loan.get("borrowed_from", ""),
                    "can_renew": loan.get("can_renew", False),
                }
                for loan in matching
            ],
        }


class OverdueLoansBinarySensor(_LoanDueBinarySensor):
    """On when at least one loan is past its due date."""

    def _matching_loans(self, today: date) -> list[dict]:
        loans = self.coordinator.data.get("loans", [])
        matching = []
        for loan in loans:
            due_date = _parse_due_date(loan)
            if due_date is not None and due_date < today:
                matching.append(loan)
        return matching


class DueSoonLoansBinarySensor(_LoanDueBinarySensor):
    """On when at least one loan is due within DUE_SOON_DAYS (and not overdue)."""

    def _matching_loans(self, today: date) -> list[dict]:
        loans = self.coordinator.data.get("loans", [])
        matching = []
        for loan in loans:
            due_date = _parse_due_date(loan)
            if due_date is None:
                continue
            days_left = (due_date - today).days
            if 0 <= days_left <= DUE_SOON_DAYS:
                matching.append(loan)
        return matching


class ReservationsReadyForPickupBinarySensor(
    HelgebibliotekenEntity, BinarySensorEntity
):
    """On when at least one reservation is ready to be picked up."""

    def __init__(
        self,
        coordinator: HelgebibliotekenDataUpdateCoordinator,
        entity_description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize the reservation binary sensor."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{entity_description.key}"
        )

    def _matching_reservations(self) -> list[dict]:
        """Return reservations that are ready for pickup."""
        reservations = self.coordinator.data.get("reservations", [])
        return [
            reservation
            for reservation in reservations
            if is_reservation_ready_for_pickup(reservation)
        ]

    @property
    def is_on(self) -> bool:
        """Return True if any reservation is ready for pickup."""
        if not self.coordinator.data:
            return False
        return bool(self._matching_reservations())

    @property
    def extra_state_attributes(self) -> dict:
        """Return count and details of reservations ready for pickup."""
        if not self.coordinator.data:
            return {"count": 0, "reservations": []}

        matching = self._matching_reservations()
        return {
            "count": len(matching),
            "reservations": [
                {
                    "reservation_id": reservation.get("reservation_id", ""),
                    "title": reservation.get("title", ""),
                    "author": reservation.get("author", ""),
                    "pickup_branch": reservation.get("pickup_branch", ""),
                    "pickup_number": reservation.get("pickup_number", ""),
                    "pickup_expiry_date": reservation.get("pickup_expiry_date", ""),
                    "status": reservation.get("status", ""),
                }
                for reservation in matching
            ],
        }
