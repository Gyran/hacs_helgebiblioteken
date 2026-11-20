"""Diagnostics support for HelGe-biblioteken."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import HelgebibliotekenConfigEntry

TO_REDACT = {CONF_USERNAME, CONF_PASSWORD, "title", "author", "loan_id", "unique_id"}


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant,
    entry: HelgebibliotekenConfigEntry,
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator = entry.runtime_data.coordinator
    data = coordinator.data if isinstance(coordinator.data, dict) else {}
    loans = data.get("loans") or []
    reservations = data.get("reservations") or []
    last_update = coordinator.last_update_time
    return {
        "entry": async_redact_data(
            {"title": entry.title, "data": dict(entry.data)}, TO_REDACT
        ),
        "version": entry.runtime_data.integration.version.string
        if entry.runtime_data.integration.version
        else None,
        "last_update_success": coordinator.last_update_success,
        "last_update_time": last_update.isoformat() if last_update else None,
        "data_keys": sorted(data),
        "loan_count": len(loans),
        "reservation_count": len(reservations),
        "loans": [async_redact_data(dict(loan), TO_REDACT) for loan in loans],
        "reservations": [
            async_redact_data(dict(item), TO_REDACT) for item in reservations
        ],
    }
