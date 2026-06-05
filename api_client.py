import json
import os
import time

import requests

os.makedirs("data", exist_ok=True)

HEADERS = {"X-Super-Client": "seaf-daily-briefing", "X-Super-Contact": "seaf-daily-briefing"}

ENDPOINTS = [
    ("https://api.helldivers2.dev/api/v1/planets", "data/planets.json"),
    ("https://api.helldivers2.dev/api/v1/campaigns", "data/campaigns.json"),
    ("https://api.helldivers2.dev/api/v1/assignments", "data/assignments.json"),
    ("https://api.helldivers2.dev/api/v2/space-stations", "data/dss.json"),
    ("https://api.helldivers2.dev/api/v1/war", "data/war.json"),
]

def fetch_all():
    for i, (url, path) in enumerate(ENDPOINTS):
        if i > 0:
            time.sleep(0.5)
        for _ in range(3):
            response = requests.get(url, headers=HEADERS)
            if response.status_code != 429:
                break
            wait = int(response.headers.get('Retry-After', 5))
            time.sleep(wait)
        response.raise_for_status()
        with open(path, "w") as f:
            json.dump(response.json(), f)


if __name__ == "__main__":
    fetch_all()
