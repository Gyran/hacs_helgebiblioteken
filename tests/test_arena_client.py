"""Arena request and loan-row parsing, aligned with helge-biblioteken-mcp."""

from __future__ import annotations

import asyncio
from typing import Self

import pytest
from bs4 import BeautifulSoup

from custom_components.helgebiblioteken.api import (
    HelgebibliotekenApiClient,
    HelgebibliotekenApiClientCommunicationError,
    is_lte3m_challenge,
    prepare_arena_request,
    unwrap_wicket_response,
    with_p_auth,
)

LOAN_HTML = """
<html><body>
<span class="arena-login-greeting">Hej</span>
<a class="arena-logout-link">Logga ut</a>
<div id="p_p_id_loansWicket_WAR_arenaportlet_">
  <table>
    <tr class="arena-renewal-true arena-loan-overdue-false" id="loan-row-id-1">
      <td class="arena-renewal-loan">
        <span class="arena-record-id">1050859</span>
        <div class="arena-record-title"><span>Chilizombier</span></div>
        <div class="arena-record-author">
          <span class="arena-value">Landgreen, Emil</span>
        </div>
        <div class="arena-record-year"><span class="arena-value">2026</span></div>
        <div class="arena-record-media"><span class="arena-value">Bok</span></div>
        <div class="arena-renewal-branch">
          <span class="arena-value">Gävle stadsbibliotek 2026-09-02</span>
        </div>
      </td>
      <td class="arena-renewal-date">
        <span class="arena-renewal-date-value">2026-09-30</span>
      </td>
      <td class="arena-renewal-status">
        <input
          type="submit"
          onclick="window.location.href='/renewLoan'; return false"
        />
        <span class="arena-renewal-status-message">Återstående antal omlån: 3</span>
      </td>
    </tr>
    <tr class="arena-renewal-false arena-loan-overdue-true" id="loan-row-id-2">
      <td>
        <span class="arena-record-id">111111</span>
        <div class="arena-record-title"><span>Kan inte förnyas</span></div>
      </td>
      <td><span class="arena-renewal-date-value">2026-08-20</span></td>
      <td class="arena-renewal-status">
        <span class="arena-renewal-status-message">Återstående antal omlån: 0</span>
      </td>
    </tr>
  </table>
</div>
<div class="arena-record-container">
  <span class="arena-record-id">773324</span>
  <div class="arena-record-title"><span>Basketbollar</span></div>
  <div>
    <span class="arena-field">Hämtnummer</span>
    <span class="arena-value">4220</span>
  </div>
  <div>
    <span class="arena-field">Hämtas före</span>
    <span class="arena-value">2026-09-15</span>
  </div>
</div>
</body></html>
"""


class _Response:
    """Minimal aiohttp response for one request."""

    def __init__(self, body: str, *, status: int = 200) -> None:
        self._body = body
        self.status = status
        self.url = "https://www.helgebiblioteken.se/"
        self.headers: dict[str, str] = {}

    async def text(self) -> str:
        return self._body

    async def read(self) -> bytes:
        return self._body.encode()

    def raise_for_status(self) -> None:
        return None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> bool:
        return False


class _Session:
    """Records the method aiohttp would send."""

    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, url: str, **_kwargs: object) -> _Response:
        self.calls.append((method, url))
        return self.response


def test_get_with_query_becomes_empty_post() -> None:
    url, method, data = prepare_arena_request(
        "https://www.helgebiblioteken.se/protected/my-account/overview?p_auth=1"
    )
    assert method == "POST"
    assert url.endswith("?p_auth=1")
    assert data == {}


def test_plain_get_stays_get() -> None:
    _url, method, data = prepare_arena_request("https://www.helgebiblioteken.se/")
    assert method == "GET"
    assert data is None


def test_with_p_auth_appends_token_once() -> None:
    html = 'Liferay.authToken = "abc def";'
    assert with_p_auth("https://x.example/login", html) == (
        "https://x.example/login?p_auth=abc%20def"
    )
    assert (
        with_p_auth("https://x.example/login?p_auth=keep", html)
        == "https://x.example/login?p_auth=keep"
    )


def test_lte3m_body_is_a_communication_error() -> None:
    body = "function leastFactor(n){return n;} LTE3M=1"
    assert is_lte3m_challenge(body) is True
    session = _Session(_Response(body))
    client = HelgebibliotekenApiClient("1212121234", "1234", session)  # type: ignore[arg-type]
    with pytest.raises(
        HelgebibliotekenApiClientCommunicationError, match="JS access check"
    ):
        asyncio.run(client._async_request("https://www.helgebiblioteken.se/"))


def test_query_url_is_posted() -> None:
    session = _Session(_Response("<html></html>"))
    client = HelgebibliotekenApiClient("1212121234", "1234", session)  # type: ignore[arg-type]
    asyncio.run(
        client._async_request(
            "https://www.helgebiblioteken.se/protected/my-account/overview?p_auth=1"
        )
    )
    assert session.calls[0][0] == "POST"


def test_wicket_ajax_cdata_is_unwrapped() -> None:
    raw = "<ajax-response><![CDATA[<span>loan</span>]]></ajax-response>"
    assert unwrap_wicket_response(raw) == "<span>loan</span>"


def test_loan_row_uses_arena_selectors() -> None:
    client = HelgebibliotekenApiClient("1212121234", "1234", object())  # type: ignore[arg-type]
    soup = BeautifulSoup(LOAN_HTML, "html.parser")
    portlet = soup.find(id="p_p_id_loansWicket_WAR_arenaportlet_")
    rows = client._parse_loan_rows(portlet)
    assert rows[0]["loan_id"] == "1050859"
    assert rows[0]["title"] == "Chilizombier"
    assert rows[0]["due_date"] == "2026-09-30"
    assert rows[0]["renewal_count"] == 3
    assert rows[0]["can_renew"] is True
    assert rows[0]["overdue"] is False
    assert "renewLoan" in rows[0]["renew_url"]
    assert rows[1]["loan_id"] == "111111"
    assert rows[1]["can_renew"] is False
    assert rows[1]["overdue"] is True
    assert rows[1]["renewal_count"] == 0
    assert rows[1]["renew_url"] is None


def test_reservation_aliases_for_pickup() -> None:
    client = HelgebibliotekenApiClient("1212121234", "1234", object())  # type: ignore[arg-type]
    soup = BeautifulSoup(LOAN_HTML, "html.parser")
    parsed = client._parse_reservation_containers(soup)
    assert parsed[0]["pickup_number"] == "4220"
    assert parsed[0]["pickup_expiry_date"] == "2026-09-15"
