import json
import os
from datetime import datetime

from flask import Flask, jsonify, render_template, request

from api_client import fetch_all
from data_parser import parse_all
from formatter import format_discord, format_video

app = Flask(__name__)

CLASSIFICATIONS_PATH = "data/classifications.json"

state = {
    "snapshot1_defense": {},
    "snapshot1_time": None,
    "classifications": {},
    "last_outputs": None,
}


def _load_classifications():
    if os.path.exists(CLASSIFICATIONS_PATH):
        with open(CLASSIFICATIONS_PATH) as f:
            data = json.load(f)
        return {
            k: ("large" if v is True else "none") if isinstance(v, bool) else v
            for k, v in data.items()
        }
    return {}


def _save_classifications(classifications):
    os.makedirs("data", exist_ok=True)
    with open(CLASSIFICATIONS_PATH, "w") as f:
        json.dump(classifications, f, indent=2)


def _get_classification_items(parsed_data):
    items = {}
    for planet in parsed_data.get("planets", []):
        for hazard in planet.get("hazards", []):
            if not hazard.get("name") or hazard["name"] == "None":
                continue
            key = f"hazard_{hazard['name']}"
            if key not in items:
                items[key] = {
                    "label": hazard["name"],
                    "description": hazard["description"],
                }
    return items


@app.route("/")
def index():
    state["classifications"] = _load_classifications()
    return render_template(
        "index.html",
        classifications=state["classifications"],
        outputs=state["last_outputs"],
    )


@app.route("/refresh", methods=["POST"])
def refresh():
    try:
        fetch_all()
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

    state["snapshot1_time"] = datetime.now()

    with open("data/planets.json") as f:
        raw_planets = json.load(f)

    snapshot1_defense = {}
    for p in raw_planets:
        event = p.get("event")
        if event and event.get("eventType") == 1:
            snapshot1_defense[p["index"]] = event["health"]
    state["snapshot1_defense"] = snapshot1_defense

    parsed = parse_all()
    items = _get_classification_items(parsed)

    saved = state["classifications"]
    items_with_state = {
        key: {
            **item,
            "tier": saved.get(key, "none"),
            "is_new": key not in saved,
        }
        for key, item in items.items()
    }

    return jsonify({"status": "ok", "items": items_with_state})


@app.route("/fetch2", methods=["POST"])
def fetch2():
    if state["snapshot1_time"] is None:
        return jsonify({"status": "error", "message": "No first snapshot — run Refresh first"}), 400

    try:
        fetch_all()
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

    snapshot2_time = datetime.now()
    parsed = parse_all()

    elapsed = (snapshot2_time - state["snapshot1_time"]).total_seconds()
    if elapsed > 0:
        for planet in parsed["planets"]:
            if not planet["is_defense"] or not planet.get("event"):
                continue
            idx = planet["index"]
            health1 = state["snapshot1_defense"].get(idx)
            health2 = planet["event"]["health"]
            if health1 is not None and health2 is not None and health1 > health2:
                net_rate = (health1 - health2) / elapsed
                planet["liberation_time_hours"] = (health2 / net_rate) / 3600

    discord_text = format_discord(parsed, state["classifications"])
    video_text = format_video(parsed, state["classifications"])
    state["last_outputs"] = {"discord": discord_text, "video": video_text}

    return jsonify({"status": "ok", "discord": discord_text, "video": video_text})


@app.route("/save_classifications", methods=["POST"])
def save_classifications():
    data = request.get_json()
    key = data.get("key")
    value = data.get("value")
    if key is None or value is None:
        return jsonify({"status": "error", "message": "Missing key or value"}), 400
    if value not in ("large", "small", "none"):
        return jsonify({"status": "error", "message": "Invalid tier value"}), 400
    state["classifications"][key] = value
    _save_classifications(state["classifications"])
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
