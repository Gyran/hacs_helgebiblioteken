"""Helpers for HelGe-biblioteken reservations."""

from __future__ import annotations

from typing import Any

# Status values seen while waiting in queue (not ready for pickup).
_WAITING_STATUS_TOKENS = frozenset({"aktiv", "active", "väntar", "waiting"})

# Status substrings that indicate a reservation is ready to pick up.
_READY_STATUS_TOKENS = (
    "att hämta",
    "klar att hämta",
    "redo att hämta",
    "kan hämtas",
    "hämtklar",
    "at pick-up",
    "ready for pickup",
    "available for pickup",
)


def is_reservation_ready_for_pickup(reservation: dict[str, Any]) -> bool:
    """Return True when reservation appears ready for pickup."""
    pickup_number = str(reservation.get("pickup_number", "")).strip()
    if pickup_number:
        return True

    pickup_expiry_date = reservation.get("pickup_expiry_date")
    if pickup_expiry_date:
        return True

    status = str(reservation.get("status", "")).strip().lower()
    if not status or status in _WAITING_STATUS_TOKENS:
        return False

    return any(token in status for token in _READY_STATUS_TOKENS)
