import json
import os
import time

import requests

os.makedirs("data", exist_ok=True)

HEADERS = {"X-Super-Client": "seaf-daily-briefing", "X-Super-Contact": "seaf-daily-briefing"}
TIMEOUT = 10

ENDPOINTS = [
    ("https://api.helldivers2.dev/api/v1/planets",       "data/planets.json"),
    ("https://api.helldivers2.dev/api/v1/campaigns",     "data/campaigns.json"),
    ("https://api.helldivers2.dev/api/v1/assignments",   "data/assignments.json"),
    ("https://api.helldivers2.dev/api/v2/space-stations","data/dss.json"),
    ("https://api.helldivers2.dev/api/v1/war",           "data/war.json"),
    ("https://api.helldivers2.dev/api/v1/dispatches",    "data/dispatches.json"),
]

# Raw Arrowhead API — supplementary source for data helldivers2.dev doesn't expose
# (planet active effects now; Tier-2 failover later). Isolated so an outage here
# can NEVER break the core helldivers2.dev pipeline.
RAW_API_BASE = "https://api.live.prod.thehelldiversgame.com"
RAW_HEADERS = {"Accept-Language": "en-US", "User-Agent": "seaf-daily-briefing"}
PLANET_EFFECTS_PATH = "data/planet_effects.json"


class ApiError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def _fetch_with_retry(url, timeout=TIMEOUT):
    for _ in range(3):
        try:
            response = requests.get(url, headers=HEADERS, timeout=timeout)
        except requests.exceptions.Timeout:
            raise ApiError(f"Request timed out after {timeout}s", status_code=None)
        except requests.exceptions.ConnectionError:
            raise ApiError("Cannot reach helldivers2.dev — check your connection", status_code=None)

        if response.status_code == 429:
            wait = int(response.headers.get("Retry-After", 5))
            time.sleep(wait)
            continue

        if not response.ok:
            raise ApiError(f"HTTP {response.status_code} from API", status_code=response.status_code)

        return response

    raise ApiError("Still rate-limited after 3 retries", status_code=429)


def ping():
    """Lightweight connectivity check — fetches only the war endpoint."""
    _fetch_with_retry("https://api.helldivers2.dev/api/v1/war", timeout=5)


def _fetch_raw_status(timeout=TIMEOUT):
    """The seam for ALL raw-API data. Fetches the WarSeason Status dict
    (planetActiveEffects now; planetStatus/Events/Attacks/Regions for the future
    failover). Raises ApiError on failure."""
    try:
        wid = requests.get(f"{RAW_API_BASE}/api/WarSeason/current/WarID", headers=RAW_HEADERS, timeout=timeout)
        if not wid.ok:
            raise ApiError(f"HTTP {wid.status_code} from raw API (WarID)", status_code=wid.status_code)
        war_id = wid.json()["id"]
        status = requests.get(f"{RAW_API_BASE}/api/WarSeason/{war_id}/Status", headers=RAW_HEADERS, timeout=timeout)
        if not status.ok:
            raise ApiError(f"HTTP {status.status_code} from raw API (Status)", status_code=status.status_code)
        return status.json()
    except requests.exceptions.Timeout:
        raise ApiError("Raw API request timed out", status_code=None)
    except requests.exceptions.ConnectionError:
        raise ApiError("Cannot reach the raw Arrowhead API", status_code=None)


def fetch_planet_effects():
    """Supplementary, ISOLATED fetch: planet active effects → data/planet_effects.json.
    Any failure is swallowed and the last-good cache is left intact, so the core
    pipeline is unaffected. Returns True on success, False on failure."""
    try:
        status = _fetch_raw_status()
    except ApiError:
        return False
    payload = {
        "war_id": status.get("warId"),
        "fetched_at": time.time(),
        "effects": status.get("planetActiveEffects") or [],  # [{index, galacticEffectId}]
    }
    with open(PLANET_EFFECTS_PATH, "w") as f:
        json.dump(payload, f)
    return True


def fetch_all():
    for i, (url, path) in enumerate(ENDPOINTS):
        if i > 0:
            time.sleep(0.5)
        response = _fetch_with_retry(url)
        with open(path, "w") as f:
            json.dump(response.json(), f)
    fetch_planet_effects()  # supplementary; never raises, never blocks core data


if __name__ == "__main__":
    fetch_all()
