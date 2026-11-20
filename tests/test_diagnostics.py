"""Tests for diagnostics redaction."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from custom_components.helgebiblioteken.diagnostics import (
    async_get_config_entry_diagnostics,
)


def test_diagnostics_redacts_credentials_and_titles() -> None:
    coordinator = SimpleNamespace(
        data={
            "loans": [{"title": "Secret Book", "loan_id": "42", "due": "2026-12-01"}],
            "reservations": [],
        },
        last_update_success=True,
        last_update_time=datetime(2026, 11, 20, tzinfo=UTC),
    )
    entry = SimpleNamespace(
        title="8001011234",
        data={"username": "8001011234", "password": "hunter2"},
        runtime_data=SimpleNamespace(
            coordinator=coordinator,
            integration=SimpleNamespace(version=None),
        ),
    )
    result = asyncio.run(async_get_config_entry_diagnostics(None, entry))
    text = str(result)
    assert "hunter2" not in text
    assert "8001011234" not in text
    assert "Secret Book" not in text
    assert result["loan_count"] == 1
    assert result["loans"][0]["due"] == "2026-12-01"
