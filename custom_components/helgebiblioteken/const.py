"""Constants for helgebiblioteken."""

import json
from logging import Logger, getLogger
from pathlib import Path
from typing import Final

LOGGER: Logger = getLogger(__package__)

DOMAIN: Final[str] = "helgebiblioteken"
ATTRIBUTION: Final[str] = "Data provided by HelGe-biblioteken"
USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Read version from manifest for frontend module registration
_MANIFEST_PATH = Path(__file__).parent / "manifest.json"
with _MANIFEST_PATH.open(encoding="utf-8") as _f:
    INTEGRATION_VERSION: Final[str] = json.load(_f).get("version", "0.0.0")

# Base URL for frontend resources (Lovelace card)
URL_BASE: Final[str] = f"/{DOMAIN}"

# JavaScript modules to register with Lovelace (storage mode)
JSMODULES: Final[list[dict[str, str]]] = [
    {
        "name": "Helgebiblioteken Loans Card",
        "filename": "helgebiblioteken-loans-card.js",
        "version": INTEGRATION_VERSION,
    },
    {
        "name": "Helgebiblioteken Reservations Card",
        "filename": "helgebiblioteken-reservations-card.js",
        "version": INTEGRATION_VERSION,
    },
]
