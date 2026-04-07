"""API Client for HelGe-biblioteken."""

from __future__ import annotations

import asyncio
import re
import socket
from datetime import UTC, datetime
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
        search_area = login_portlet if login_portlet else soup
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
                    field_name = inp_name if inp_name else inp_id
                    if field_name:
                        form_fields[field_name] = self._username
                        _LOGGER.debug("Found potential username field: %s", field_name)
                elif "password" in inp_type:
                    field_name = inp_name if inp_name else inp_id
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
        search_area = login_portlet if login_portlet else soup

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
        search_area = (
            login_form if login_form else (login_portlet if login_portlet else soup)
        )

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
                or "personnummer" in id_lower
                or ("signin" in id_lower and "text" in inp.get("type", "").lower())
            ):
                field_name = name if name else inp_id
                if field_name:
                    form_fields[field_name] = self._username
                    _LOGGER.debug("Found personnummer field: %s", field_name)
            elif (
                "pin" in name_lower
                or "pin" in id_lower
                or ("signin" in id_lower and "password" in inp.get("type", "").lower())
            ):
                field_name = name if name else inp_id
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

        # Check if we're still on the login page - if so, login failed
        if "patronlogin" in url_lower and (
            "signin" in url_lower or "wicket:interface" in url_lower
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

        # Also check for login indicators in HTML (and not still on login page)
        if ("mina sidor" in html_lower or "logga ut" in html_lower) and (
            "/start" not in url_lower or "patronlogin" not in url_lower
        ):
            self._logged_in = True
            _LOGGER.debug("Login verified successfully - found login indicators")
            return

        _LOGGER.error(
            "Login verification failed - response does not contain "
            "expected login indicators"
        )
        _LOGGER.debug("Final URL: %s", final_url)
        _LOGGER.debug("Response preview (first 500 chars): %s", html[:500])
        msg = "Login failed - unable to verify session"
        raise HelgebibliotekenApiClientAuthenticationError(msg)

    async def async_get_loans(self) -> list[dict[str, Any]]:  # noqa: PLR0912, PLR0915
        """Get current loans from HelGe-biblioteken, following pagination."""
        _LOGGER.debug("Fetching loans")
        for attempt in range(2):
            await self.async_login()
            try:
                async with asyncio.timeout(TIMEOUT):
                    all_loans: list[dict[str, Any]] = []
                    current_url = f"{self.BASE_URL}/protected/my-account/overview"
                    page_num = 1

                    while page_num <= MAX_LOAN_PAGES:
                        _LOGGER.debug(
                            "Fetching loans page %d from %s", page_num, current_url
                        )

                        async with self._session.get(current_url) as response:
                            _LOGGER.debug("Page response status: %s", response.status)
                            _verify_response_or_raise(response)
                            html = await response.text()
                            _LOGGER.debug("Page HTML length: %d bytes", len(html))
                            soup = BeautifulSoup(html, "html.parser")

                        # Check if we're still logged in
                        html_lower = html.lower()
                        not_logged_in = (
                            "du har inte loggat in" in html_lower
                            or "not logged in" in html_lower
                        )
                        if not_logged_in:
                            _LOGGER.warning("Session expired - not logged in on page")
                            self._logged_in = False
                            _raise_session_expired()

                        loans_portlet = self._find_loans_portlet(soup)
                        if not loans_portlet:
                            if page_num == 1:
                                _LOGGER.warning("Loans portlet not found in HTML")
                                all_divs = soup.find_all(
                                    "div", id=re.compile(r".*loan.*", re.IGNORECASE)
                                )
                                _LOGGER.debug(
                                    "Found %d divs with 'loan' in ID", len(all_divs)
                                )
                            break

                        portlet_text = loans_portlet.get_text().lower()
                        if "du har inte loggat in" in portlet_text:
                            _LOGGER.warning("Not logged in message found in portlet")
                            self._logged_in = False
                            _raise_session_expired()

                        # On first page only: "Lån saknas" means no loans at all
                        if page_num == 1:
                            no_loans_msg = loans_portlet.find(
                                string=re.compile(r"lån saknas", re.IGNORECASE)
                            )
                            if no_loans_msg:
                                _LOGGER.debug(
                                    "No loans message found - user has no loans"
                                )
                                return []

                        page_loans = self._parse_loans(loans_portlet)
                        _LOGGER.debug(
                            "Parsed %d loans on page %d", len(page_loans), page_num
                        )
                        all_loans.extend(page_loans)

                        next_url = self._find_next_page_link(loans_portlet, current_url)
                        if not next_url or next_url == current_url:
                            break
                        current_url = next_url
                        page_num += 1

                    _LOGGER.debug("Total loans after pagination: %d", len(all_loans))
                    return all_loans

            except HelgebibliotekenApiClientAuthenticationError:
                if attempt == 0:
                    _LOGGER.warning(
                        "Session expired during loan fetch, re-logging in and "
                        "retrying once"
                    )
                    self._logged_in = False
                    continue
                raise
            except TimeoutError as exception:
                msg = f"Timeout error fetching loans - {exception}"
                raise HelgebibliotekenApiClientCommunicationError(msg) from exception
            except (aiohttp.ClientError, socket.gaierror) as exception:
                msg = f"Error fetching loans - {exception}"
                raise HelgebibliotekenApiClientCommunicationError(msg) from exception
            except Exception as exception:  # pylint: disable=broad-except
                msg = f"Unexpected error fetching loans - {exception}"
                raise HelgebibliotekenApiClientError(msg) from exception

        msg = "Loan fetch failed after retry"
        raise HelgebibliotekenApiClientError(msg)

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

    def _parse_loans(  # noqa: PLR0912, PLR0915
        self, loans_portlet: Any
    ) -> list[dict[str, Any]]:
        """Parse loan information from the portlet."""
        loans = []

        # Check if portlet contains "not logged in" message
        portlet_text = loans_portlet.get_text()
        if "du har inte loggat in" in portlet_text.lower():
            _LOGGER.warning("Portlet contains 'not logged in' message")
            return loans

        # Find the table with caption "Mina lån"
        loans_table = loans_portlet.find("table")
        if not loans_table:
            _LOGGER.debug("No loans table found in portlet")
            # Log portlet structure for debugging
            portlet_html_preview = str(loans_portlet)[:500]
            _LOGGER.debug("Portlet HTML preview: %s", portlet_html_preview)
            return loans

        _LOGGER.debug("Found loans table, parsing rows")
        # Data rows in tbody, header in thead; fallback: all rows
        tbody = loans_table.find("tbody")
        rows = tbody.find_all("tr") if tbody else loans_table.find_all("tr")

        _LOGGER.debug("Found %d table rows", len(rows))
        for row in rows:
            # Skip header rows - check if row is in thead or if all cells are th
            if row.find_parent("thead"):
                _LOGGER.debug("Skipping header row (in thead)")
                continue

            # Check if all cells are th (header row) vs having td cells (data row)
            all_cells = row.find_all(["th", "td"])
            th_cells = row.find_all("th")
            td_cells = row.find_all("td")

            # If all cells are th, it's a header row
            if len(th_cells) == len(all_cells) and len(all_cells) > 0:
                _LOGGER.debug("Skipping header row (all cells are th)")
                continue

            # Prefer td cells; some rows have th scope="row" + td
            cells = td_cells if td_cells else all_cells

            if len(cells) < MIN_TABLE_CELLS:
                _LOGGER.debug(
                    "Skipping row with %d cells (need %d)",
                    len(cells),
                    MIN_TABLE_CELLS,
                )
                continue

            # First cell may be th+checkbox; then title/author, due, status
            # Find the cell with title (contains link or "Av:")
            title_cell = None
            for cell in cells:
                cell_text = cell.get_text()
                if cell.find("a") or "Av:" in cell_text:
                    title_cell = cell
                    break

            if not title_cell:
                title_cell = cells[0]  # Fallback to first cell

            # Extract title from link
            title_link = title_cell.find("a")
            title = title_link.get_text(strip=True) if title_link else ""

            # Extract details from text
            cell_text = title_cell.get_text()
            # Match author, stopping before "Utgivningsår:" field
            author_match = re.search(
                r"Av:\s*(.+?)(?=\s+Utgivningsår:|$)", cell_text, re.DOTALL
            )
            # Match year (just digits)
            year_match = re.search(r"Utgivningsår:\s*(\d+)", cell_text)
            # Match media type, stopping before "Lånad på:" field
            media_match = re.search(
                r"Medietyp:\s*(.+?)(?=\s+Lånad på:|$)", cell_text, re.DOTALL
            )
            # Match borrowed info (library and date), stopping at end or newline
            borrowed_match = re.search(r"Lånad på:\s*([^\n]+)", cell_text)

            author = author_match.group(1).strip() if author_match else ""
            year = None
            if year_match:
                try:
                    year = int(year_match.group(1))
                except (ValueError, IndexError):
                    year = None
            media_type = media_match.group(1).strip() if media_match else ""
            borrowed_info = borrowed_match.group(1).strip() if borrowed_match else ""

            # Parse borrowed date from borrowed_info (format: "Library YYYY-MM-DD")
            borrowed_date = None
            borrowed_library = borrowed_info
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})", borrowed_info)
            if date_match:
                date_str = date_match.group(1)
                # Validate it's a valid date format
                try:
                    datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
                    borrowed_date = date_str
                except ValueError:
                    borrowed_date = None
                borrowed_library = borrowed_info.replace(date_str, "").strip()

            # Find due date cell (contains date pattern YYYY-MM-DD)
            due_date = None
            status_text = ""
            for cell in cells:
                cell_text = cell.get_text(strip=True)
                # Check if it's a date cell (just a date, no other text)
                if re.match(r"^\d{4}-\d{2}-\d{2}$", cell_text):
                    # Validate it's a valid date format
                    try:
                        datetime.strptime(cell_text, "%Y-%m-%d").replace(tzinfo=UTC)
                        due_date = cell_text
                    except ValueError:
                        due_date = None
                # Check if it's status cell (contains "Låna om" or renewal info)
                elif "låna om" in cell_text.lower() or "omlån" in cell_text.lower():
                    status_text = cell_text

            # If we didn't find status, check last cell
            if not status_text and len(cells) > 1:
                status_cell = cells[-1]
                status_text = status_cell.get_text(strip=True)

            can_renew = (
                "kan inte lånas om" not in status_text.lower() if status_text else True
            )

            # Extract renewal count from status text
            # (e.g., "Återstående antal omlån: 3")
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
                    except (ValueError, IndexError):
                        renewal_count = None

            loan = {
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
            }
            _LOGGER.debug("Parsed loan: %s by %s (due: %s)", title, author, due_date)
            loans.append(loan)

        _LOGGER.debug("Total loans parsed: %d", len(loans))
        return loans

    async def async_get_data(self) -> dict[str, Any]:
        """Get data from the API - returns loans information."""
        _LOGGER.debug("Getting data from API")
        loans = await self.async_get_loans()
        data = {
            "loans": loans,
            "loan_count": len(loans),
        }
        _LOGGER.debug("Returning data with %d loans", len(loans))
        return data
