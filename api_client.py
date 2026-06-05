import json
import os

import requests

os.makedirs("data", exist_ok=True)

response = requests.get("https://api.helldivers2.dev/api/v1/planets", headers={"X-Super-Client": "seaf-daily-briefing", "X-Super-Contact": "seaf-daily-briefing"})
response.raise_for_status()

with open("data/war_status.json", "w") as f:
    json.dump(response.json(), f)
