"""Reservation parsing and session-lock serialization."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from bs4 import BeautifulSoup

from custom_components.helgebiblioteken.api import (
    HelgebibliotekenApiClient,
    HelgebibliotekenApiClientError,
    HelgebibliotekenApiClientLoanNotRenewableError,
)


def _field(label: str, value: str) -> str:
    return (
        f'<div><span class="arena-field">{label}</span>'
        f'<span class="arena-value">{value}</span></div>'
    )


RESERVATION_HTML = f"""
<div id="p_p_id_reservationsWicket_WAR_arenaportlet_">
  <div class="arena-record-container">
    <span class="arena-record-id">998877</span>
    <div class="arena-record-title"><span>Sommarboken</span></div>
    {_field("Av:", "Jansson, Tove")}
    {_field("Utgivningsår", "1972")}
    {_field("Språk", "Svenska")}
    {_field("Medietyp", "Bok")}
    {_field("Hämtställe", "Sandviken")}
    {_field("Köplats", "3 (av 5 exemplar)")}
    {_field("Giltig från", "2026-10-01")}
    {_field("Giltig till", "inte ett datum")}
    {_field("Status", "Aktiv")}
  </div>
  <div class="arena-record-container">
    <div class="arena-record-title"><span>Utan id</span></div>
    {_field("Köplats", "okänd")}
  </div>
</div>
"""


def _client() -> HelgebibliotekenApiClient:
    return HelgebibliotekenApiClient("1212121234", "1234", object())  # type: ignore[arg-type]


def test_reservation_fields_are_parsed() -> None:
    soup = BeautifulSoup(RESERVATION_HTML, "html.parser")
    portlet = _client()._find_reservations_portlet(soup)
    first, second = _client()._parse_reservations(portlet)

    assert first["reservation_id"] == "998877"
    assert first["title"] == "Sommarboken"
    assert first["author"] == "Jansson, Tove"
    assert first["publication_year"] == 1972
    assert first["language"] == "Svenska"
    assert first["pickup_branch"] == "Sandviken"
    assert (first["queue_position"], first["queue_total"]) == (3, 5)
    assert first["valid_from"] == "2026-10-01"
    assert first["valid_to"] is None  # invalid dates are dropped, not passed through
    assert first["status"] == "Aktiv"

    assert second["reservation_id"] is None
    assert second["queue_text"] == "okänd"
    assert (second["queue_position"], second["queue_total"]) == (None, None)


def test_poll_and_renewal_do_not_overlap() -> None:
    client = _client()
    active = 0
    max_active = 0

    async def _tracked(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return [], []

    client._async_get_account_data_locked = _tracked  # type: ignore[method-assign]
    client._async_renew_loans_locked = _tracked  # type: ignore[method-assign]

    async def _run() -> None:
        await asyncio.gather(
            client.async_get_data(),
            client.async_renew_loans(["1"]),
            client.async_get_loans(),
        )

    asyncio.run(_run())
    assert max_active == 1


def _renew_result(**buckets: list[str]) -> dict[str, list[str]]:
    keys = ("renewed", "failed", "skipped", "not_found", "ambiguous", "feedback")
    return {key: buckets.get(key, []) for key in keys}


@pytest.mark.parametrize("bucket", ["not_found", "ambiguous", "skipped"])
def test_unrenewable_loan_is_a_validation_style_error(bucket: str) -> None:
    client = _client()

    async def _fake(_ids: list[str]) -> dict[str, list[str]]:
        return _renew_result(**{bucket: ["42"]})

    client.async_renew_loans = _fake  # type: ignore[method-assign]
    with pytest.raises(HelgebibliotekenApiClientLoanNotRenewableError):
        asyncio.run(client.async_renew_loan("42"))


def test_failed_renewal_attempt_stays_a_plain_api_error() -> None:
    client = _client()

    async def _fake(_ids: list[str]) -> dict[str, list[str]]:
        return _renew_result(failed=["42"])

    client.async_renew_loans = _fake  # type: ignore[method-assign]
    with pytest.raises(HelgebibliotekenApiClientError) as info:
        asyncio.run(client.async_renew_loan("42"))
    assert not isinstance(info.value, HelgebibliotekenApiClientLoanNotRenewableError)
