"""Regression tests for login success detection."""

from unittest.mock import MagicMock

import pytest

from custom_components.helgebiblioteken.api import (
    HelgebibliotekenApiClient,
    HelgebibliotekenApiClientAuthenticationError,
    HelgebibliotekenApiClientSessionExpiredError,
)

SUCCESS_URL = (
    "https://www.helgebiblioteken.se/protected/my-account/overview?p_p_auth=abc"
)
LOGIN_PAGE_URL = (
    "https://www.helgebiblioteken.se/start"
    "?p_p_id=patronLogin_WAR_arenaportlet"
    "&p_p_lifecycle=1"
    "&wicket:interface=:0:signInPanel"
)

SUCCESS_HTML_WITH_JS_ERROR = """
<html>
  <head>
    <script>
      window.onerror = function (Error) { console.error(Error); };
    </script>
  </head>
  <body>
    <div class="error">Library hours</div>
    <div>Mina lån</div>
  </body>
</html>
"""

LOGIN_HTML_BAD_PIN = """
<html>
  <body>
    <div id="patronLogin_WAR_arenaportlet">
      <form>
        <span>Felaktigt personnummer eller PIN</span>
        <input name="openTextUsername" type="text">
      </form>
    </div>
  </body>
</html>
"""

LOGIN_HTML_NO_CREDENTIAL_ERROR = """
<html>
  <body>
    <div id="patronLogin_WAR_arenaportlet">
      <form>
        <script>console.error("debug");</script>
        <input name="openTextUsername" type="text">
      </form>
    </div>
  </body>
</html>
"""


def _client() -> HelgebibliotekenApiClient:
    return HelgebibliotekenApiClient("1212121234", "1234", MagicMock())


def test_success_url_with_js_error_is_not_auth_failure() -> None:
    client = _client()
    client._verify_login_success(SUCCESS_HTML_WITH_JS_ERROR, SUCCESS_URL)
    assert client._logged_in is True


def test_visible_pin_error_is_auth_failure() -> None:
    client = _client()
    with pytest.raises(HelgebibliotekenApiClientAuthenticationError, match="Invalid"):
        client._verify_login_success(LOGIN_HTML_BAD_PIN, LOGIN_PAGE_URL)
    assert client._logged_in is False


def test_login_page_without_credential_text_is_not_auth_failure() -> None:
    client = _client()
    with pytest.raises(HelgebibliotekenApiClientSessionExpiredError):
        client._verify_login_success(LOGIN_HTML_NO_CREDENTIAL_ERROR, LOGIN_PAGE_URL)
    assert client._logged_in is False


def test_patron_greeting_is_login_success() -> None:
    client = _client()
    html = """
    <html><body>
      <span class="arena-login-greeting">Hej</span>
      <a class="arena-logout-link">Logga ut</a>
    </body></html>
    """
    client._verify_login_success(html, "https://www.helgebiblioteken.se/start")
    assert client._logged_in is True


def test_arena_not_logged_in_phrase_is_auth_failure() -> None:
    client = _client()
    html = "<html><body>Du blev inte inloggad</body></html>"
    with pytest.raises(HelgebibliotekenApiClientAuthenticationError, match="Invalid"):
        client._verify_login_success(html, "https://www.helgebiblioteken.se/start")
    assert client._logged_in is False
