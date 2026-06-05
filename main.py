import json
import os
from datetime import datetime

from flask import Flask, jsonify, render_template, request

from api_client import fetch_all
from data_parser import parse_all
from formatter import format_discord, format_video, get_theater_data

app = Flask(__name__)

CLASSIFICATIONS_PATH = "data/classifications.json"
FLAVOR_PATH = "data/flavor.json"

state = {
    "snapshot1_defense": {},
    "snapshot1_time": None,
    "classifications": {},
    "flavor": {},
    "last_parsed": None,
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


def _load_flavor():
    if os.path.exists(FLAVOR_PATH):
        with open(FLAVOR_PATH) as f:
            data = json.load(f)
        data.setdefault("theaters", {})
        data.setdefault("planets", {})
        data.setdefault("limits", {})
        data.setdefault("planet_notes", {})
        return data
    return {"theaters": {}, "planets": {}, "limits": {}, "planet_notes": {}}


def _save_flavor(flavor):
    os.makedirs("data", exist_ok=True)
    with open(FLAVOR_PATH, "w") as f:
        json.dump(flavor, f, indent=2)


def _get_classification_items(raw_planets):
    items = {}
    for planet in raw_planets:
        for hazard in planet.get("hazards", []):
            name = hazard.get("name", "")
            if not name or name == "None":
                continue
            key = f"hazard_{name}"
            if key not in items:
                items[key] = {
                    "label": name,
                    "description": hazard.get("description", ""),
                }
    return items


@app.route("/")
def index():
    state["classifications"] = _load_classifications()
    state["flavor"] = _load_flavor()
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
    items = _get_classification_items(raw_planets)

    saved = state["classifications"]
    items_with_state = {
        key: {
            **item,
            "tier": saved.get(key, "none"),
            "is_new": key not in saved,
        }
        for key, item in items.items()
    }

    theaters = get_theater_data(parsed, state["flavor"].get("limits", {}))

    return jsonify({
        "status": "ok",
        "items": items_with_state,
        "theaters": theaters,
        "flavor": state["flavor"],
    })


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

    state["last_parsed"] = parsed
    theaters = get_theater_data(parsed, state["flavor"].get("limits", {}))
    discord_text = format_discord(parsed, state["classifications"], state["flavor"])
    video_text = format_video(parsed, state["classifications"], state["flavor"])
    state["last_outputs"] = {"discord": discord_text, "video": video_text}

    return jsonify({
        "status": "ok",
        "discord": discord_text,
        "video": video_text,
        "theaters": theaters,
        "flavor": state["flavor"],
    })


@app.route("/reformat", methods=["POST"])
def reformat():
    if state["last_parsed"] is None:
        return jsonify({"status": "error", "message": "No data — run Refresh first"}), 400
    discord_text = format_discord(state["last_parsed"], state["classifications"], state["flavor"])
    video_text = format_video(state["last_parsed"], state["classifications"], state["flavor"])
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


@app.route("/save_flavor", methods=["POST"])
def save_flavor():
    data = request.get_json()
    scope = data.get("scope")
    key = data.get("key")
    value = data.get("value", "")
    if scope not in ("theaters", "planets", "planet_notes") or not key:
        return jsonify({"status": "error", "message": "Invalid scope or key"}), 400
    if value:
        state["flavor"][scope][key] = value
    else:
        state["flavor"][scope].pop(key, None)
    _save_flavor(state["flavor"])
    return jsonify({"status": "ok"})


@app.route("/save_limit", methods=["POST"])
def save_limit():
    data = request.get_json()
    faction = data.get("faction")
    limited = data.get("limited")
    if not faction or not isinstance(limited, bool):
        return jsonify({"status": "error", "message": "Invalid request"}), 400
    if limited:
        state["flavor"]["limits"][faction] = True
    else:
        state["flavor"]["limits"].pop(faction, None)
    _save_flavor(state["flavor"])
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
