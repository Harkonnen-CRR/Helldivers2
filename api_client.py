import json
import os

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

for url, path in ENDPOINTS:
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    with open(path, "w") as f:
        json.dump(response.json(), f)
