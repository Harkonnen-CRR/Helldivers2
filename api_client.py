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


def fetch_all():
    for i, (url, path) in enumerate(ENDPOINTS):
        if i > 0:
            time.sleep(0.5)
        response = _fetch_with_retry(url)
        with open(path, "w") as f:
            json.dump(response.json(), f)


if __name__ == "__main__":
    fetch_all()
