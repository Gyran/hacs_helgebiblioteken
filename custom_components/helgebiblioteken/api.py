"""API Client for HelGe-biblioteken."""

from __future__ import annotations

import asyncio
import re
import socket
from collections import defaultdict
from datetime import UTC, date, datetime
from logging import getLogger
from typing import Any, NoReturn
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup

TIMEOUT = 10
MIN_TEXT_LENGTH = 10
MIN_TABLE_CELLS = 3
MIN_LOGIN_INPUTS = 2
MAX_DEBUG_VALUE_LEN = 50
MAX_LOAN_PAGES = 20  # Safety limit when following pagination
MAX_RESERVATION_PAGES = 20  # Safety limit when following pagination
OVERVIEW_PATH = "/protected/my-account/overview"

_LOGGER = getLogger(__name__)


class HelgebibliotekenApiClientError(Exception):
    """Exception to indicate a general API error."""


class HelgebibliotekenApiClientCommunicationError(
    HelgebibliotekenApiClientError,
):
    """Exception to indicate a communication error."""


class HelgebibliotekenApiClientAuthenticationError(
    HelgebibliotekenApiClientError,
):
    """Exception to indicate an authentication error."""


def _raise_session_expired() -> NoReturn:
    msg = "Session expired, please try again"
    raise HelgebibliotekenApiClientAuthenticationError(msg)


def _verify_response_or_raise(response: aiohttp.ClientResponse) -> None:
    """Verify that the response is valid."""
    if response.status in (401, 403):
        msg = "Invalid credentials"
        raise HelgebibliotekenApiClientAuthenticationError(
            msg,
        )
    response.raise_for_status()


class HelgebibliotekenApiClient:
    """API Client for HelGe-biblioteken."""

    BASE_URL = "https://www.helgebiblioteken.se"

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialize the API client."""
        self._username = username  # Personnummer
        self._password = password  # PIN
        self._session = session
        self._logged_in = False

    async def async_login(self) -> None:  # noqa: PLR0912, PLR0915
        """Login to HelGe-biblioteken."""
        # Never log credential values (username/password) in debug output.
        if self._logged_in:
            _LOGGER.debug("Already logged in, skipping login")
            return

        _LOGGER.debug("Starting login process")
        try:
            # First, get the login page to get the form structure
            _LOGGER.debug("Fetching login page from %s", self.BASE_URL)
            async with asyncio.timeout(TIMEOUT):
                async with self._session.get(f"{self.BASE_URL}/") as response:
                    _LOGGER.debug("Login page response status: %s", response.status)
                    _verify_response_or_raise(response)
                    html = await response.text()
                    _LOGGER.debug("Login page HTML length: %d bytes", len(html))
                    soup = BeautifulSoup(html, "html.parser")

                # Find the actual login form to get the correct action URL
                login_form = None
                login_portlet = soup.find(
                    "div", {"id": re.compile(r"patronLogin.*", re.IGNORECASE)}
                )
                if login_portlet:
                    forms_in_portlet = login_portlet.find_all("form")
                    if forms_in_portlet:
                        login_form = forms_in_portlet[0]

                # If no form found in portlet, search for form containing login fields
                if not login_form:
                    username_input = soup.find(
                        "input",
                        {"name": re.compile(r".*openTextUsername.*", re.IGNORECASE)},
                    )
                    if username_input:
                        login_form = username_input.find_parent("form")

                # Get the form action URL, or construct default
                if login_form and login_form.get("action"):
                    login_url = login_form.get("action")
                    if login_url.startswith("/"):
                        login_url = f"{self.BASE_URL}{login_url}"
                    _LOGGER.debug("Using form action URL: %s", login_url)
                else:
                    # Fallback: Wicket URL with interface :0: not :2:
                    login_url = (
                        f"{self.BASE_URL}/start"
                        "?p_p_id=patronLogin_WAR_arenaportlet"
                        "&p_p_lifecycle=1"
                        "&p_p_state=normal"
                        "&p_p_mode=view"
                        "&_patronLogin_WAR_arenaportlet__wu="
                        "%2FpatronLogin%2F%3Fwicket%3Ainterface%3D%3A0%3AsignInPanel"
                        "%3AsignInFormPanel%3AsignInForm%3A%3AIFormSubmitListener%3A%3A"
                    )
                    _LOGGER.debug("Using constructed URL: %s", login_url)

                # Prepare form data
                form_data = aiohttp.FormData()

                # Extract Wicket hidden fields (CSRF tokens, etc.) from the login form
                if login_form:
                    hidden_inputs = login_form.find_all("input", {"type": "hidden"})
                    _LOGGER.debug(
                        "Found %d hidden fields in login form", len(hidden_inputs)
                    )
                else:
                    # Use portlet or whole page to find hidden inputs
                    if login_portlet:
                        hidden_inputs = login_portlet.find_all(
                            "input", {"type": "hidden"}
                        )
                    else:
                        hidden_inputs = soup.find_all("input", {"type": "hidden"})
                    _LOGGER.debug(
                        "Found %d hidden fields (fallback)", len(hidden_inputs)
                    )

                for hidden in hidden_inputs:
                    name = hidden.get("name")
                    value = hidden.get("value", "")
                    if name:
                        form_data.add_field(name, value)
                        _LOGGER.debug(
                            "Added hidden field: %s = %s",
                            name,
                            value[:MAX_DEBUG_VALUE_LEN]
                            if len(value) > MAX_DEBUG_VALUE_LEN
                            else value,
                        )

                # Log some HTML structure for debugging
                all_forms = soup.find_all("form")
                _LOGGER.debug("Found %d forms in HTML", len(all_forms))
                all_inputs = soup.find_all("input")
                _LOGGER.debug("Found %d input elements in HTML", len(all_inputs))
                if all_inputs:
                    # Log first few input names/ids for debugging
                    sample_inputs = all_inputs[:5]
                    for inp in sample_inputs:
                        _LOGGER.debug(
                            "Sample input: name=%s, id=%s, type=%s",
                            inp.get("name", ""),
                            inp.get("id", ""),
                            inp.get("type", ""),
                        )

                form_fields = self._extract_form_fields(soup)
                _LOGGER.debug(
                    "Extracted form fields: %s",
                    form_fields.keys() if form_fields else "None",
                )

                if not form_fields:
                    form_fields = self._find_wicket_fields(soup)

                if not form_fields:
                    form_fields = self._find_fallback_fields(soup)

                self._add_form_fields(form_data, form_fields)

                # Log which form fields were found and will be submitted
                if form_fields:
                    _LOGGER.debug(
                        "Will submit form fields: %s", list(form_fields.keys())
                    )
                else:
                    _LOGGER.warning("No form fields found - using fallback field names")

                # Perform login
                _LOGGER.debug("Submitting login form to %s", login_url)
                async with self._session.post(
                    login_url,
                    data=form_data,
                    allow_redirects=True,
                ) as response:
                    _LOGGER.debug("Login response status: %s", response.status)
                    final_url = str(response.url)
                    _LOGGER.debug("Login response final URL: %s", final_url)
                    html = await response.text()
                    _LOGGER.debug("Login response HTML length: %d bytes", len(html))
                    self._verify_login_success(html, final_url)

                    # Verify session by trying to access protected page
                    _LOGGER.debug("Verifying session by accessing protected page")
                    async with self._session.get(
                        f"{self.BASE_URL}/protected/my-account/overview"
                    ) as verify_response:
                        verify_html = await verify_response.text()
                        verify_html_lower = verify_html.lower()
                        if "du har inte loggat in" in verify_html_lower:
                            _LOGGER.error(
                                "Login verification failed - "
                                "cannot access protected page"
                            )
                            self._logged_in = False
                            msg = "Login failed - session not valid"
                            raise HelgebibliotekenApiClientAuthenticationError(msg)  # noqa: TRY301
                        _LOGGER.debug("Session verified - can access protected page")

                    _LOGGER.debug("Login successful")

        except HelgebibliotekenApiClientAuthenticationError:
            raise
        except TimeoutError as exception:
            msg = f"Timeout error during login - {exception}"
            raise HelgebibliotekenApiClientCommunicationError(msg) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            msg = f"Error during login - {exception}"
            raise HelgebibliotekenApiClientCommunicationError(msg) from exception
        except Exception as exception:  # pylint: disable=broad-except
            msg = f"Unexpected error during login - {exception}"
            raise HelgebibliotekenApiClientError(msg) from exception

    def _find_wicket_fields(self, soup: BeautifulSoup) -> dict[str, str]:
        """Try to find fields by looking for Wicket-generated IDs."""
        form_fields = {}

        # First try to find login portlet/panel
        login_portlet = soup.find(
            "div", {"id": re.compile(r"patronLogin.*", re.IGNORECASE)}
        )
        if not login_portlet:
            login_portlet = soup.find(
                "div", {"id": re.compile(r".*signIn.*", re.IGNORECASE)}
            )

        # Search within portlet if found
        search_area = login_portlet or soup
        all_inputs = search_area.find_all("input")

        for inp in all_inputs:
            inp_id = inp.get("id", "")
            inp_name = inp.get("name", "")
            inp_type = inp.get("type", "").lower()

            # Skip search fields
            if "search" in inp_id.lower() or "search" in inp_name.lower():
                continue

            # Look for Wicket field patterns related to signIn
            if "signIn" in inp_id.lower() or "signIn" in inp_name.lower():
                if "text" in inp_type:
                    field_name = inp_name or inp_id
                    if field_name:
                        form_fields[field_name] = self._username
                        _LOGGER.debug("Found potential username field: %s", field_name)
                elif "password" in inp_type:
                    field_name = inp_name or inp_id
                    if field_name:
                        form_fields[field_name] = self._password
                        _LOGGER.debug("Found potential password field: %s", field_name)
        return form_fields

    def _find_fallback_fields(self, soup: BeautifulSoup) -> dict[str, str]:
        """Last resort: try to find fields by position within login portlet."""
        form_fields = {}
        _LOGGER.warning("Could not find form fields, trying common patterns")

        # Try to find login portlet first
        login_portlet = soup.find(
            "div", {"id": re.compile(r"patronLogin.*", re.IGNORECASE)}
        )
        if not login_portlet:
            login_portlet = soup.find(
                "div", {"id": re.compile(r".*signIn.*", re.IGNORECASE)}
            )

        # Search within portlet if found, otherwise search all
        search_area = login_portlet or soup

        # Filter out search inputs
        all_inputs = search_area.find_all("input", {"type": ["text", "password"]})
        # Remove search-related inputs
        login_inputs = [
            inp
            for inp in all_inputs
            if "search" not in (inp.get("name", "") + inp.get("id", "")).lower()
        ]

        if len(login_inputs) >= MIN_LOGIN_INPUTS:
            text_inputs = [inp for inp in login_inputs if inp.get("type") == "text"]
            password_inputs = [
                inp for inp in login_inputs if inp.get("type") == "password"
            ]
            if text_inputs and password_inputs:
                username_field = text_inputs[0].get("name") or text_inputs[0].get("id")
                password_field = password_inputs[0].get("name") or password_inputs[
                    0
                ].get("id")
                if username_field:
                    form_fields[username_field] = self._username
                if password_field:
                    form_fields[password_field] = self._password
                _LOGGER.debug(
                    "Using fallback field detection: %s",
                    list(form_fields.keys()),
                )
        return form_fields

    def _add_form_fields(
        self, form_data: aiohttp.FormData, form_fields: dict[str, str]
    ) -> None:
        """Add form fields to the form data."""
        if not form_fields:
            _LOGGER.warning("Using generic field names as last resort")
            form_data.add_field("personnummer", self._username)
            form_data.add_field("pin", self._password)
        else:
            for key, value in form_fields.items():
                form_data.add_field(key, value)
                _LOGGER.debug("Added form field: %s", key)

    def _extract_form_fields(  # noqa: PLR0912
        self, soup: BeautifulSoup
    ) -> dict[str, str]:
        """Extract form field names from the login page."""
        form_fields = {}

        # First, try to find the login portlet/panel
        # Look for div with patronLogin portlet ID or signInPanel
        login_portlet = soup.find(
            "div", {"id": re.compile(r"patronLogin.*", re.IGNORECASE)}
        )
        if not login_portlet:
            login_portlet = soup.find(
                "div", {"id": re.compile(r".*signIn.*", re.IGNORECASE)}
            )

        # Look for login form - it might be in a dialog/modal or portlet
        forms = soup.find_all("form")
        login_form = None

        # First try to find form within the login portlet
        if login_portlet:
            forms_in_portlet = login_portlet.find_all("form")
            if forms_in_portlet:
                login_form = forms_in_portlet[0]
                _LOGGER.debug("Found login form within portlet")

        # If not found, try to find form with login-related content
        if not login_form:
            for form in forms:
                form_text = form.get_text().lower()
                form_id = form.get("id", "").lower()
                if (
                    "personnummer" in form_text
                    or "pin" in form_text
                    or "logga in" in form_text
                    or "signin" in form_id
                    or "patronlogin" in form_id
                ):
                    login_form = form
                    _LOGGER.debug("Found login form by content")
                    break

        # If no specific login form found, search within portlet or all inputs
        search_area = login_form or (login_portlet or soup)

        # Find all text and password inputs within the search area
        login_inputs = search_area.find_all(
            "input", {"type": "text"}
        ) + search_area.find_all("input", {"type": "password"})

        _LOGGER.debug("Found %d input fields to check", len(login_inputs))

        # Log all input fields found for debugging
        if login_inputs:
            _LOGGER.debug("Input fields found:")
            for inp in login_inputs:
                inp_name = inp.get("name", "")
                inp_id = inp.get("id", "")
                inp_type = inp.get("type", "")
                inp_placeholder = inp.get("placeholder", "")
                _LOGGER.debug(
                    "  - name='%s', id='%s', type='%s', placeholder='%s'",
                    inp_name,
                    inp_id,
                    inp_type,
                    inp_placeholder,
                )

        for inp in login_inputs:
            name = inp.get("name", "")
            inp_id = inp.get("id", "")
            name_lower = name.lower()
            id_lower = inp_id.lower()

            # Skip search fields
            if "search" in name_lower or "search" in id_lower:
                _LOGGER.debug("Skipping search field: %s", name or inp_id)
                continue

            # Check both name and id attributes for login fields
            if (
                "personnummer" in name_lower
                or "lanekort" in name_lower
                or "opentextusername" in name_lower
                or "personnummer" in id_lower
                or ("signin" in id_lower and "text" in inp.get("type", "").lower())
            ):
                field_name = name or inp_id
                if field_name:
                    form_fields[field_name] = self._username
                    _LOGGER.debug("Found personnummer field: %s", field_name)
            elif (
                "pin" in name_lower
                or "textpassword" in name_lower
                or "pin" in id_lower
                or ("signin" in id_lower and "password" in inp.get("type", "").lower())
            ):
                field_name = name or inp_id
                if field_name:
                    form_fields[field_name] = self._password
                    _LOGGER.debug("Found PIN field: %s", field_name)

        return form_fields

    def _verify_login_success(self, html: str, final_url: str) -> None:
        """Verify that login was successful."""
        html_lower = html.lower()
        url_lower = final_url.lower()
        soup = BeautifulSoup(html, "html.parser")

        # Check for error messages first - look for various error indicators
        error_indicators = [
            "felaktigt",
            "invalid",
            "fel personnummer",
            "fel pin",
            "ogiltigt",
            "error",
            "felaktig",
        ]
        for error_text in error_indicators:
            if error_text in html_lower:
                # Try to extract the actual error message
                error_elements = soup.find_all(
                    string=re.compile(error_text, re.IGNORECASE)
                )
                if error_elements:
                    error_msg = error_elements[0].strip()[:200]
                    _LOGGER.error("Login failed: %s", error_msg)
                else:
                    _LOGGER.error(
                        "Login failed: Invalid credentials detected in response"
                    )
                msg = "Invalid credentials"
                raise HelgebibliotekenApiClientAuthenticationError(msg)

        # On success, URL has p_p_auth or protected/my-account/overview
        if (
            "/protected/my-account/overview" in url_lower
            or "p_p_auth=" in url_lower
            or "arenaccount" in url_lower
        ):
            self._logged_in = True
            _LOGGER.debug("Login verified successfully - on protected page")
            return

        # Portal portlet: lifecycle=0 in redirect URL after successful sign-in
        if "patronlogin" in url_lower and "p_p_lifecycle=0" in url_lower:
            self._logged_in = True
            _LOGGER.debug(
                "Login verified successfully - patronLogin lifecycle=0 redirect"
            )
            return

        # Check if we're still on the login page - if so, login failed
        if "patronlogin" in url_lower and (
            "p_p_lifecycle=1" in url_lower
            or "signin" in url_lower
            or "wicket:interface" in url_lower
        ):
            _LOGGER.error(
                "Login failed - still on login page after submission. "
                "Check if credentials are correct or if form fields are missing."
            )
            # Look for any visible error messages in the page
            error_divs = soup.find_all(
                "div", class_=re.compile(r"error|alert|warning", re.IGNORECASE)
            )
            if error_divs:
                for error_div in error_divs[:3]:  # Check first 3 error divs
                    error_text = error_div.get_text(strip=True)
                    if error_text:
                        _LOGGER.debug("Found error message: %s", error_text[:200])
            msg = "Login failed - still on login page"
            raise HelgebibliotekenApiClientAuthenticationError(msg)

        _LOGGER.error(
            "Login verification failed - response does not contain "
            "expected login indicators"
        )
        _LOGGER.debug("Final URL: %s", final_url)
        _LOGGER.debug("Response preview (first 500 chars): %s", html[:500])
        msg = "Login failed - unable to verify session"
        raise HelgebibliotekenApiClientAuthenticationError(msg)

    @property
    def _overview_url(self) -> str:
        """Return the account overview URL."""
        return f"{self.BASE_URL}{OVERVIEW_PATH}"

    async def _fetch_overview_html(self, url: str) -> tuple[str, BeautifulSoup]:
        """Fetch an overview page and return HTML plus parsed soup."""
        async with asyncio.timeout(TIMEOUT):
            async with self._session.get(url) as response:
                _LOGGER.debug("Overview page response status: %s", response.status)
                _verify_response_or_raise(response)
                html = await response.text()
                _LOGGER.debug("Overview page HTML length: %d bytes", len(html))
        return html, BeautifulSoup(html, "html.parser")

    def _verify_overview_logged_in(self, html: str) -> None:
        """Raise if the overview page indicates the session expired."""
        html_lower = html.lower()
        if "du har inte loggat in" in html_lower or "not logged in" in html_lower:
            _LOGGER.warning("Session expired - not logged in on overview page")
            self._logged_in = False
            _raise_session_expired()

    def _verify_portlet_logged_in(self, portlet: Any) -> None:
        """Raise if a portlet indicates the session expired."""
        if "du har inte loggat in" in portlet.get_text().lower():
            _LOGGER.warning("Not logged in message found in portlet")
            self._logged_in = False
            _raise_session_expired()

    def _advance_loans_page(
        self,
        current_url: str,
        page_num: int,
        soup: BeautifulSoup,
        all_loans: list[dict[str, Any]],
    ) -> tuple[str | None, int]:
        """Parse one loans page and return the next URL, if any."""
        loans_portlet = self._find_loans_portlet(soup)
        if not loans_portlet:
            if page_num == 1:
                _LOGGER.warning("Loans portlet not found in HTML")
            return None, page_num

        self._verify_portlet_logged_in(loans_portlet)

        if page_num == 1:
            no_loans_msg = loans_portlet.find(
                string=re.compile(r"lån saknas", re.IGNORECASE)
            )
            if no_loans_msg:
                _LOGGER.debug("No loans message found - user has no loans")
                return None, page_num

        page_loans = self._parse_loans(loans_portlet)
        _LOGGER.debug("Parsed %d loans on page %d", len(page_loans), page_num)
        all_loans.extend(page_loans)

        next_url = self._find_next_page_link(loans_portlet, current_url)
        if not next_url or next_url == current_url:
            return None, page_num + 1
        return next_url, page_num + 1

    def _advance_reservations_page(
        self,
        current_url: str,
        page_num: int,
        soup: BeautifulSoup,
        all_reservations: list[dict[str, Any]],
    ) -> tuple[str | None, int]:
        """Parse one reservations page and return the next URL, if any."""
        reservations_portlet = self._find_reservations_portlet(soup)
        if not reservations_portlet:
            if page_num == 1:
                _LOGGER.warning("Reservations portlet not found in HTML")
            return None, page_num

        self._verify_portlet_logged_in(reservations_portlet)

        if page_num == 1:
            no_reservations_msg = reservations_portlet.find(
                string=re.compile(
                    r"reservationer saknas|inga reservationer",
                    re.IGNORECASE,
                )
            )
            if no_reservations_msg:
                _LOGGER.debug("No reservations message found")
                return None, page_num

        page_reservations = self._parse_reservations(reservations_portlet)
        _LOGGER.debug(
            "Parsed %d reservations on page %d",
            len(page_reservations),
            page_num,
        )
        all_reservations.extend(page_reservations)

        next_url = self._find_next_page_link(reservations_portlet, current_url)
        if not next_url or next_url == current_url:
            return None, page_num + 1
        return next_url, page_num + 1

    async def _async_get_account_data(  # noqa: PLR0912, PLR0915
        self,
        *,
        include_loans: bool = True,
        include_reservations: bool = True,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Fetch loans and reservations, sharing overview requests when possible."""
        _LOGGER.debug(
            "Fetching account data (loans=%s, reservations=%s)",
            include_loans,
            include_reservations,
        )
        for attempt in range(2):
            await self.async_login()
            try:
                all_loans: list[dict[str, Any]] = []
                all_reservations: list[dict[str, Any]] = []
                loans_url = self._overview_url if include_loans else None
                reservations_url = self._overview_url if include_reservations else None
                loans_page_num = 0
                reservations_page_num = 0
                seen_loan_urls: set[str] = set()
                seen_reservation_urls: set[str] = set()

                while True:
                    loans_active = (
                        include_loans
                        and loans_url is not None
                        and loans_page_num < MAX_LOAN_PAGES
                    )
                    reservations_active = (
                        include_reservations
                        and reservations_url is not None
                        and reservations_page_num < MAX_RESERVATION_PAGES
                    )
                    if not loans_active and not reservations_active:
                        break

                    if (
                        loans_active
                        and reservations_active
                        and loans_url == reservations_url
                    ):
                        if loans_url in seen_loan_urls:
                            _LOGGER.warning(
                                "Loan pagination loop detected at %s", loans_url
                            )
                            loans_url = None
                            reservations_url = None
                            continue
                        seen_loan_urls.add(loans_url)
                        seen_reservation_urls.add(reservations_url)
                        _LOGGER.debug(
                            "Fetching shared overview page for loans page %d "
                            "and reservations page %d from %s",
                            loans_page_num + 1,
                            reservations_page_num + 1,
                            loans_url,
                        )
                        html, soup = await self._fetch_overview_html(loans_url)
                        self._verify_overview_logged_in(html)
                        loans_url, loans_page_num = self._advance_loans_page(
                            loans_url,
                            loans_page_num + 1,
                            soup,
                            all_loans,
                        )
                        reservations_url, reservations_page_num = (
                            self._advance_reservations_page(
                                reservations_url,
                                reservations_page_num + 1,
                                soup,
                                all_reservations,
                            )
                        )
                        continue

                    if loans_active and loans_url is not None:
                        if loans_url in seen_loan_urls:
                            _LOGGER.warning(
                                "Loan pagination loop detected at %s", loans_url
                            )
                            loans_url = None
                            continue
                        seen_loan_urls.add(loans_url)
                        _LOGGER.debug(
                            "Fetching loans page %d from %s",
                            loans_page_num + 1,
                            loans_url,
                        )
                        html, soup = await self._fetch_overview_html(loans_url)
                        self._verify_overview_logged_in(html)
                        loans_url, loans_page_num = self._advance_loans_page(
                            loans_url,
                            loans_page_num + 1,
                            soup,
                            all_loans,
                        )

                    if reservations_active and reservations_url is not None:
                        if reservations_url in seen_reservation_urls:
                            _LOGGER.warning(
                                "Reservation pagination loop detected at %s",
                                reservations_url,
                            )
                            reservations_url = None
                            continue
                        seen_reservation_urls.add(reservations_url)
                        _LOGGER.debug(
                            "Fetching reservations page %d from %s",
                            reservations_page_num + 1,
                            reservations_url,
                        )
                        html, soup = await self._fetch_overview_html(reservations_url)
                        self._verify_overview_logged_in(html)
                        reservations_url, reservations_page_num = (
                            self._advance_reservations_page(
                                reservations_url,
                                reservations_page_num + 1,
                                soup,
                                all_reservations,
                            )
                        )

                _LOGGER.debug(
                    "Total account data after pagination: %d loans, %d reservations",
                    len(all_loans),
                    len(all_reservations),
                )
                return all_loans, all_reservations  # noqa: TRY300

            except HelgebibliotekenApiClientAuthenticationError:
                if attempt == 0:
                    _LOGGER.warning(
                        "Session expired during account fetch, re-logging in and "
                        "retrying once"
                    )
                    self._logged_in = False
                    continue
                raise
            except TimeoutError as exception:
                msg = f"Timeout error fetching account data - {exception}"
                raise HelgebibliotekenApiClientCommunicationError(msg) from exception
            except (aiohttp.ClientError, socket.gaierror) as exception:
                msg = f"Error fetching account data - {exception}"
                raise HelgebibliotekenApiClientCommunicationError(msg) from exception
            except Exception as exception:  # pylint: disable=broad-except
                msg = f"Unexpected error fetching account data - {exception}"
                raise HelgebibliotekenApiClientError(msg) from exception

        msg = "Account data fetch failed after retry"
        raise HelgebibliotekenApiClientError(msg)

    async def async_get_loans(self) -> list[dict[str, Any]]:
        """Get current loans from HelGe-biblioteken, following pagination."""
        loans, _ = await self._async_get_account_data(include_reservations=False)
        return loans

    async def async_get_reservations(self) -> list[dict[str, Any]]:
        """Get current reservations from HelGe-biblioteken, following pagination."""
        _, reservations = await self._async_get_account_data(include_loans=False)
        return reservations

    def _find_loans_portlet(self, soup: BeautifulSoup) -> Any:
        """Find the loans portlet in the HTML."""
        # Try multiple strategies to find the loans portlet
        # Strategy 1: Find by ID pattern
        loans_portlet = soup.find(
            "div", {"id": re.compile(r"loansWicket.*", re.IGNORECASE)}
        )
        if loans_portlet:
            portlet_id = loans_portlet.get("id")
            _LOGGER.debug("Found portlet by ID pattern: %s", portlet_id)
            return loans_portlet

        # Strategy 2: Find by class containing "loans"
        loans_portlet = soup.find("div", class_=re.compile(r".*loans.*", re.IGNORECASE))
        if loans_portlet:
            _LOGGER.debug("Found portlet by class pattern")
            return loans_portlet

        # Strategy 3: Find div containing "Mina lån" heading
        mina_lan_heading = soup.find(
            "h2", string=re.compile(r"mina lån", re.IGNORECASE)
        )
        if mina_lan_heading:
            _LOGGER.debug("Found 'Mina lån' heading, looking for parent portlet")
            # Find the parent portlet div
            parent = mina_lan_heading.find_parent(
                "div", class_=re.compile(r"portlet", re.IGNORECASE)
            )
            if parent:
                _LOGGER.debug("Found portlet via heading parent")
                return parent

        # Strategy 4: Find any div with id containing "loan"
        loans_portlet = soup.find("div", {"id": re.compile(r".*loan.*", re.IGNORECASE)})
        if loans_portlet:
            portlet_id = loans_portlet.get("id")
            _LOGGER.debug("Found portlet by ID containing 'loan': %s", portlet_id)
            return loans_portlet

        _LOGGER.debug("Could not find loans portlet with any strategy")
        return None

    def _find_reservations_portlet(self, soup: BeautifulSoup) -> Any:
        """Find the reservations portlet in the HTML."""
        reservations_portlet = soup.find(
            "div", {"id": re.compile(r"reservationsWicket.*", re.IGNORECASE)}
        )
        if reservations_portlet:
            portlet_id = reservations_portlet.get("id")
            _LOGGER.debug("Found reservations portlet by ID pattern: %s", portlet_id)
            return reservations_portlet

        reservations_portlet = soup.find(
            "div", class_=re.compile(r".*reservation.*", re.IGNORECASE)
        )
        if reservations_portlet:
            _LOGGER.debug("Found reservations portlet by class pattern")
            return reservations_portlet

        heading = soup.find(
            "h2", string=re.compile(r"mina reservationer", re.IGNORECASE)
        )
        if heading:
            _LOGGER.debug(
                "Found 'Mina reservationer' heading, looking for parent portlet"
            )
            parent = heading.find_parent(
                "div", class_=re.compile(r"portlet", re.IGNORECASE)
            )
            if parent:
                _LOGGER.debug("Found reservations portlet via heading parent")
                return parent

        reservations_portlet = soup.find(
            "div", {"id": re.compile(r".*reserv.*", re.IGNORECASE)}
        )
        if reservations_portlet:
            portlet_id = reservations_portlet.get("id")
            _LOGGER.debug(
                "Found reservations portlet by ID containing 'reserv': %s",
                portlet_id,
            )
            return reservations_portlet

        _LOGGER.debug("Could not find reservations portlet with any strategy")
        return None

    def _find_next_page_link(self, loans_portlet: Any, current_url: str) -> str | None:
        """Find the 'next page' link in the loans portlet for pagination."""
        if not loans_portlet:
            return None
        # Common patterns: "Nästa" (Swedish), "Next", "»", U+203A, or rel="next"
        next_patterns = ("nästa", "next", "»", "\u203a", "följande")
        for anchor in loans_portlet.find_all("a", href=True):
            href = anchor.get("href", "").strip()
            if (
                not href
                or href.startswith("#")
                or href.lower().startswith("javascript:")
            ):
                continue
            text = anchor.get_text(strip=True).lower()
            title = (anchor.get("title") or anchor.get("aria-label") or "").lower()
            combined = f"{text} {title}"
            if any(p in combined for p in next_patterns):
                _LOGGER.debug("Found next page link: %s", href[:80])
                return urljoin(current_url, href)
            if anchor.get("rel") == "next":
                _LOGGER.debug("Found next page link (rel=next): %s", href[:80])
                return urljoin(current_url, href)
        return None

    def _parse_loan_id_from_title_cell(self, title_cell: Any) -> str | None:
        """Parse the leading bibliographic ID from the title cell text."""
        title_text = title_cell.get_text(" ", strip=True)
        match = re.match(r"^\s*(\d+)", title_text)
        return match.group(1) if match else None

    def _parse_loan_rows(  # noqa: PLR0912, PLR0915
        self, loans_portlet: Any
    ) -> list[dict[str, Any]]:
        """Parse table rows with loan and renewal metadata."""
        rows_data: list[dict[str, Any]] = []
        loans_table = loans_portlet.find("table")
        if not loans_table:
            return rows_data

        tbody = loans_table.find("tbody")
        rows = tbody.find_all("tr") if tbody else loans_table.find_all("tr")

        for row in rows:
            if row.find_parent("thead"):
                continue
            all_cells = row.find_all(["th", "td"])
            th_cells = row.find_all("th")
            td_cells = row.find_all("td")
            if len(th_cells) == len(all_cells) and len(all_cells) > 0:
                continue
            cells = td_cells or all_cells
            if len(cells) < MIN_TABLE_CELLS:
                continue

            title_cell = None
            for cell in cells:
                cell_text = cell.get_text()
                if cell.find("a") or "Av:" in cell_text:
                    title_cell = cell
                    break
            if not title_cell:
                title_cell = cells[0]

            title_link = title_cell.find("a")
            title = title_link.get_text(strip=True) if title_link else ""
            loan_id = self._parse_loan_id_from_title_cell(title_cell)

            cell_text = title_cell.get_text()
            author_match = re.search(
                r"Av:\s*(.+?)(?=\s+Utgivningsår:|$)", cell_text, re.DOTALL
            )
            year_match = re.search(r"Utgivningsår:\s*(\d+)", cell_text)
            media_match = re.search(
                r"Medietyp:\s*(.+?)(?=\s+Lånad på:|$)", cell_text, re.DOTALL
            )
            borrowed_match = re.search(r"Lånad på:\s*([^\n]+)", cell_text)

            author = author_match.group(1).strip() if author_match else ""
            year = None
            if year_match:
                try:
                    year = int(year_match.group(1))
                except ValueError, IndexError:
                    year = None
            media_type = media_match.group(1).strip() if media_match else ""
            borrowed_info = borrowed_match.group(1).strip() if borrowed_match else ""

            borrowed_date = None
            borrowed_library = borrowed_info
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})", borrowed_info)
            if date_match:
                date_str = date_match.group(1)
                try:
                    datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
                    borrowed_date = date_str
                except ValueError:
                    borrowed_date = None
                borrowed_library = borrowed_info.replace(date_str, "").strip()

            due_date = None
            status_text = ""
            for cell in cells:
                inner_text = cell.get_text(strip=True)
                if re.match(r"^\d{4}-\d{2}-\d{2}$", inner_text):
                    try:
                        datetime.strptime(inner_text, "%Y-%m-%d").replace(tzinfo=UTC)
                        due_date = inner_text
                    except ValueError:
                        due_date = None
                elif "låna om" in inner_text.lower() or "omlån" in inner_text.lower():
                    status_text = inner_text

            if not status_text and len(cells) > 1:
                status_text = cells[-1].get_text(strip=True)

            can_renew = (
                "kan inte lånas om" not in status_text.lower() if status_text else True
            )
            renewal_count = None
            if status_text:
                renewal_match = re.search(
                    r"(?:Återstående antal omlån|omlån):\s*(\d+)",
                    status_text,
                    re.IGNORECASE,
                )
                if renewal_match:
                    try:
                        renewal_count = int(renewal_match.group(1))
                    except ValueError, IndexError:
                        renewal_count = None

            checkbox = row.find("input", {"name": "loansCheckboxGroup"})
            checkbox_value = checkbox.get("value") if checkbox else None

            # Per-row "Låna om" is a GET to a Wicket ILinkListener link embedded
            # in the submit button's onclick (window.location.href='...').
            renew_url = None
            for submit in row.find_all("input", {"type": "submit"}):
                onclick = submit.get("onclick", "")
                href_match = re.search(
                    r"window\.location\.href\s*=\s*'([^']+renewLoan[^']*)'", onclick
                )
                if href_match:
                    renew_url = href_match.group(1)
                    break

            rows_data.append(
                {
                    "loan_id": loan_id,
                    "title": title,
                    "author": author,
                    "publication_year": year,
                    "media_type": media_type,
                    "borrowed_from": borrowed_library,
                    "borrowed_date": borrowed_date,
                    "due_date": due_date,
                    "status": status_text,
                    "can_renew": can_renew,
                    "renewal_count": renewal_count,
                    "checkbox_value": checkbox_value,
                    "renew_url": renew_url,
                }
            )
        return rows_data

    def _extract_feedback_messages(self, soup: BeautifulSoup) -> list[str]:
        """Extract feedback messages from common alert/message containers."""
        messages: list[str] = []
        for selector in ("div.feedbackPanel", "div.alert", "li.feedbackPanelERROR"):
            for node in soup.select(selector):
                text = node.get_text(" ", strip=True)
                if text and text not in messages:
                    messages.append(text)
        return messages

    def _parse_loans(self, loans_portlet: Any) -> list[dict[str, Any]]:
        """Parse loan information from the portlet."""
        portlet_text = loans_portlet.get_text()
        if "du har inte loggat in" in portlet_text.lower():
            _LOGGER.warning("Portlet contains 'not logged in' message")
            return []

        parsed_rows = self._parse_loan_rows(loans_portlet)
        loans = []
        for row in parsed_rows:
            loan = {
                "loan_id": row["loan_id"],
                "title": row["title"],
                "author": row["author"],
                "publication_year": row["publication_year"],
                "media_type": row["media_type"],
                "borrowed_from": row["borrowed_from"],
                "borrowed_date": row["borrowed_date"],
                "due_date": row["due_date"],
                "status": row["status"],
                "can_renew": row["can_renew"],
                "renewal_count": row["renewal_count"],
            }
            _LOGGER.debug(
                "Parsed loan: %s by %s (due: %s)",
                loan["title"],
                loan["author"],
                loan["due_date"],
            )
            loans.append(loan)
        _LOGGER.debug("Total loans parsed: %d", len(loans))
        return loans

    def _parse_date_field(self, value: str) -> str | None:
        """Return ISO date string if valid, else None."""
        if not value:
            return None
        try:
            datetime.strptime(value.strip(), "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            return None
        return value.strip()

    def _extract_labeled_values(self, container: Any) -> dict[str, str]:
        """Extract key/value pairs from arena-field/arena-value spans."""
        values: dict[str, str] = {}
        for field in container.find_all("span", class_="arena-field"):
            label = field.get_text(strip=True).rstrip(":")
            if not label:
                continue
            parent = field.parent
            if not parent:
                continue
            value_node = parent.find("span", class_="arena-value")
            if not value_node:
                continue
            value = value_node.get_text(" ", strip=True)
            if value:
                values[label] = value
        return values

    def _parse_queue_values(self, queue_text: str) -> tuple[int | None, int | None]:
        """Parse queue text like '1 (av 2 exemplar)' into numeric values."""
        if not queue_text:
            return None, None
        match = re.search(r"(\d+)\s*\(av\s*(\d+)", queue_text, re.IGNORECASE)
        if not match:
            return None, None
        try:
            return int(match.group(1)), int(match.group(2))
        except ValueError, IndexError:
            return None, None

    def _parse_reservation_containers(
        self, reservations_portlet: Any
    ) -> list[dict[str, Any]]:
        """Parse reservation details from arena record containers."""
        parsed_reservations: list[dict[str, Any]] = []
        containers = reservations_portlet.find_all(
            "div", class_=re.compile(r"\barena-record-container\b")
        )
        for container in containers:
            values = self._extract_labeled_values(container)

            id_node = container.find("span", class_=re.compile(r"\barena-record-id\b"))
            reservation_id = id_node.get_text(strip=True) if id_node else None
            if not reservation_id:
                reservation_id = None

            title_node = container.find(
                "div", class_=re.compile(r"\barena-record-title\b")
            )
            title = title_node.get_text(" ", strip=True) if title_node else ""

            publication_year = None
            year_text = values.get("Utgivningsår", "")
            if year_text:
                try:
                    publication_year = int(year_text)
                except ValueError:
                    publication_year = None

            queue_text = values.get("Köplats", "")
            queue_position, queue_total = self._parse_queue_values(queue_text)

            reservation = {
                "reservation_id": reservation_id,
                "title": title,
                "author": values.get("Av", ""),
                "publication_year": publication_year,
                "language": values.get("Språk", ""),
                "media_type": values.get("Medietyp", ""),
                "pickup_branch": values.get("Hämtställe", ""),
                "queue_text": queue_text,
                "queue_position": queue_position,
                "queue_total": queue_total,
                "reservation_type": values.get("Reservationstyp", ""),
                "valid_from": self._parse_date_field(values.get("Giltig från", "")),
                "valid_to": self._parse_date_field(values.get("Giltig till", "")),
                "pickup_number": values.get("Löpnummer", ""),
                "pickup_expiry_date": self._parse_date_field(
                    values.get("Hämtas senast", "")
                ),
                "status": values.get("Status", ""),
            }
            parsed_reservations.append(reservation)

        return parsed_reservations

    def _parse_reservations(self, reservations_portlet: Any) -> list[dict[str, Any]]:
        """Parse reservations from the reservations portlet."""
        portlet_text = reservations_portlet.get_text()
        if "du har inte loggat in" in portlet_text.lower():
            _LOGGER.warning("Reservations portlet contains 'not logged in' message")
            return []

        reservations = self._parse_reservation_containers(reservations_portlet)
        _LOGGER.debug("Total reservations parsed: %d", len(reservations))
        return reservations

    async def _fetch_overview_rows(self) -> list[dict[str, Any]]:
        """Fetch the overview page and return parsed loan rows."""
        current_url = f"{self.BASE_URL}/protected/my-account/overview"
        async with asyncio.timeout(TIMEOUT):
            async with self._session.get(current_url) as response:
                _verify_response_or_raise(response)
                html = await response.text()
        soup = BeautifulSoup(html, "html.parser")
        if "du har inte loggat in" in html.lower():
            self._logged_in = False
            _raise_session_expired()
        loans_portlet = self._find_loans_portlet(soup)
        if not loans_portlet:
            msg = "Could not find loans portlet"
            raise HelgebibliotekenApiClientError(msg)
        return self._parse_loan_rows(loans_portlet)

    async def _renew_single(self, loan_id: str) -> tuple[bool, list[str]]:
        """Renew one loan via its per-row Wicket link; verify with a fresh fetch."""
        current_url = f"{self.BASE_URL}/protected/my-account/overview"
        rows = await self._fetch_overview_rows()
        matches = [r for r in rows if r.get("loan_id") == loan_id]
        if len(matches) != 1:
            return False, []
        row = matches[0]
        if not row.get("renew_url") or not row.get("can_renew"):
            return False, []

        before_due = row.get("due_date")
        before_count = row.get("renewal_count")
        renew_url = urljoin(current_url, row["renew_url"])

        async with asyncio.timeout(TIMEOUT):
            async with self._session.get(renew_url, allow_redirects=True) as response:
                _verify_response_or_raise(response)
                renew_html = await response.text()
        feedback = self._extract_feedback_messages(
            BeautifulSoup(renew_html, "html.parser")
        )

        after_rows = await self._fetch_overview_rows()
        after = next((r for r in after_rows if r.get("loan_id") == loan_id), None)
        if not after:
            return False, feedback

        due_advanced = False
        after_due = after.get("due_date")
        if before_due and after_due:
            try:
                due_advanced = date.fromisoformat(after_due) > date.fromisoformat(
                    before_due
                )
            except ValueError:
                due_advanced = False
        after_count = after.get("renewal_count")
        count_decreased = (
            before_count is not None
            and after_count is not None
            and after_count < before_count
        )
        return (due_advanced or count_decreased), feedback

    def _classify_requested(
        self,
        requested_ids: list[str],
        rows: list[dict[str, Any]],
        result: dict[str, list[str]],
    ) -> list[str]:
        """Sort requested IDs into buckets; return the renewable ones."""
        row_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            if row.get("loan_id"):
                row_map[row["loan_id"]].append(row)

        selectable_ids: list[str] = []
        for loan_id in requested_ids:
            matches = row_map.get(loan_id, [])
            if not matches:
                result["not_found"].append(loan_id)
            elif len(matches) > 1:
                result["ambiguous"].append(loan_id)
            elif not matches[0].get("can_renew") or not matches[0].get("renew_url"):
                result["skipped"].append(loan_id)
            else:
                selectable_ids.append(loan_id)
        return selectable_ids

    async def async_renew_loans(  # noqa: PLR0912
        self, loan_ids: list[str]
    ) -> dict[str, Any]:
        """Renew selected loans by loan ID(s), one Wicket renewal link per loan."""
        requested_ids: list[str] = []
        for loan_id in loan_ids:
            normalized = str(loan_id).strip()
            if normalized and normalized not in requested_ids:
                requested_ids.append(normalized)
        if not requested_ids:
            msg = "No valid loan IDs provided"
            raise HelgebibliotekenApiClientError(msg)

        for attempt in range(2):
            await self.async_login()
            try:
                rows = await self._fetch_overview_rows()
                result: dict[str, list[str]] = {
                    "renewed": [],
                    "failed": [],
                    "skipped": [],
                    "not_found": [],
                    "ambiguous": [],
                    "feedback": [],
                }
                selectable_ids = self._classify_requested(requested_ids, rows, result)
                for loan_id in selectable_ids:
                    renewed, feedback = await self._renew_single(loan_id)
                    for message in feedback:
                        if message not in result["feedback"]:
                            result["feedback"].append(message)
                    bucket = "renewed" if renewed else "failed"
                    result[bucket].append(loan_id)
            except HelgebibliotekenApiClientAuthenticationError:
                if attempt == 0:
                    _LOGGER.warning(
                        "Session expired during renewal, re-logging in, retrying"
                    )
                    self._logged_in = False
                    continue
                raise
            except TimeoutError as exception:
                msg = f"Timeout error renewing loans - {exception}"
                raise HelgebibliotekenApiClientCommunicationError(msg) from exception
            except (aiohttp.ClientError, socket.gaierror) as exception:
                msg = f"Error renewing loans - {exception}"
                raise HelgebibliotekenApiClientCommunicationError(msg) from exception
            except HelgebibliotekenApiClientError:
                raise
            except Exception as exception:  # pylint: disable=broad-except
                msg = f"Unexpected error renewing loans - {exception}"
                raise HelgebibliotekenApiClientError(msg) from exception
            else:
                return result

        msg = "Loan renewal failed after retry"
        raise HelgebibliotekenApiClientError(msg)

    async def async_renew_loan(self, loan_id: str) -> dict[str, Any]:
        """Renew one loan and raise a clear error if it failed."""
        result = await self.async_renew_loans([loan_id])
        if result["renewed"]:
            return result
        if result["ambiguous"]:
            msg = f"Loan ID {loan_id} is ambiguous, multiple matching loans found"
        elif result["not_found"]:
            msg = f"Loan ID {loan_id} not found"
        elif result["skipped"]:
            msg = f"Loan ID {loan_id} cannot be renewed"
        else:
            msg = f"Renewal failed for loan ID {loan_id}"
        raise HelgebibliotekenApiClientError(msg)

    async def async_renew_due_soon(self, days: int = 3) -> dict[str, Any]:
        """Renew all renewable loans overdue or due within N days."""
        loans = await self.async_get_loans()
        today = datetime.now(UTC).date()
        due_soon_ids: list[str] = []
        for loan in loans:
            loan_id = loan.get("loan_id")
            due_date = loan.get("due_date")
            if not loan_id or not due_date or loan.get("can_renew") is False:
                continue
            try:
                due = date.fromisoformat(due_date)
            except TypeError, ValueError:
                continue
            if (due - today).days <= days and str(loan_id) not in due_soon_ids:
                due_soon_ids.append(str(loan_id))

        if not due_soon_ids:
            return {
                "renewed": [],
                "failed": [],
                "skipped": [],
                "not_found": [],
                "ambiguous": [],
                "feedback": [],
            }
        return await self.async_renew_loans(due_soon_ids)

    async def async_get_data(self) -> dict[str, Any]:
        """Get data from the API - returns loans and reservations."""
        _LOGGER.debug("Getting data from API")
        loans, reservations = await self._async_get_account_data()
        data = {
            "loans": loans,
            "loan_count": len(loans),
            "reservations": reservations,
            "reservation_count": len(reservations),
        }
        _LOGGER.debug(
            "Returning data with %d loans and %d reservations",
            len(loans),
            len(reservations),
        )
        return data
