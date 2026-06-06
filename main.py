import json
import os
from datetime import datetime

from flask import Flask, jsonify, render_template, request

from api_client import fetch_all, ping, ApiError
from data_parser import parse_all
from formatter import format_discord, format_video, get_theater_data, get_modifier_panel_data

app = Flask(__name__)

CLASSIFICATIONS_PATH = "data/classifications.json"
FLAVOR_PATH = "data/flavor.json"

state = {
    "snapshot1_health": {},
    "snapshot1_time": None,
    "classifications": {},
    "flavor": {},
    "last_parsed": None,
    "last_outputs": None,
}


def _api_error_type(status_code):
    if status_code is None:
        return "timeout"
    if status_code == 429:
        return "rate_limit"
    if status_code in (502, 503, 504):
        return "down"
    return "server_error"


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
        data.setdefault("planet_tags", {})
        data.setdefault("planet_modifiers", {})
        data.setdefault("custom_modifiers", [])
        data.setdefault("selected_dispatches", [])
        data.setdefault("free_stratagems", [])
        data.setdefault("excluded_theaters", [])
        data.setdefault("alert_titles", {
            "major_order": "PRIORITY ALERT: NEW MAJOR ORDER",
            "minor_order": "ALERT: MINOR ORDER UPDATE",
            "strategic_opportunity": "ALERT: STRATEGIC OPPORTUNITY",
        })
        # Migrate old planet_custom_modifiers (per-planet list) into new flat list
        old = data.pop("planet_custom_modifiers", {})
        if old and not data["custom_modifiers"]:
            seen = {}
            for planet_name, mods in old.items():
                if isinstance(mods, str):
                    mods = [{"text": l.strip(), "tier": "none"} for l in mods.splitlines() if l.strip()]
                for m in (mods or []):
                    text = (m.get("text") or "").strip() if isinstance(m, dict) else str(m).strip()
                    tier = m.get("tier", "none") if isinstance(m, dict) else "none"
                    if not text:
                        continue
                    key = (text, tier)
                    if key not in seen:
                        seen[key] = {"text": text, "tier": tier, "planets": []}
                    seen[key]["planets"].append(planet_name)
            data["custom_modifiers"] = list(seen.values())
        return data
    return {
        "theaters": {}, "planets": {}, "limits": {}, "planet_notes": {},
        "planet_tags": {}, "planet_modifiers": {}, "custom_modifiers": [],
        "selected_dispatches": [],
        "free_stratagems": [],
        "excluded_theaters": [],
        "alert_titles": {
            "major_order": "PRIORITY ALERT: NEW MAJOR ORDER",
            "minor_order": "ALERT: MINOR ORDER UPDATE",
            "strategic_opportunity": "ALERT: STRATEGIC OPPORTUNITY",
        },
    }


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
        alert_titles=state["flavor"].get("alert_titles", {}),
    )


@app.route("/refresh", methods=["POST"])
def refresh():
    try:
        fetch_all()
    except ApiError as e:
        return jsonify({"status": "error", "message": str(e), "error_type": _api_error_type(e.status_code)}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "error_type": "unknown"}), 200

    state["snapshot1_time"] = datetime.now()

    with open("data/planets.json") as f:
        raw_planets = json.load(f)

    snapshot1_health = {}
    for p in raw_planets:
        idx = p["index"]
        event = p.get("event")
        if event and event.get("eventType") == 1:
            snapshot1_health[idx] = event["health"]
        else:
            snapshot1_health[idx] = p["health"]
        for r in p.get("regions", []):
            snapshot1_health[f"{idx}_r{r['id']}"] = r["health"]
    state["snapshot1_health"] = snapshot1_health

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

    theaters = get_theater_data(parsed, state["flavor"].get("limits", {}), state["classifications"], state["flavor"].get("planet_modifiers", {}))
    modifier_panel = get_modifier_panel_data(parsed, state["flavor"])

    return jsonify({
        "status": "ok",
        "items": items_with_state,
        "theaters": theaters,
        "modifier_panel": modifier_panel,
        "dispatches": parsed.get("dispatches", []),
        "flavor": state["flavor"],
    })


@app.route("/fetch2", methods=["POST"])
def fetch2():
    if state["snapshot1_time"] is None:
        return jsonify({"status": "error", "message": "No first snapshot — run Refresh first", "error_type": "unknown"}), 400

    try:
        fetch_all()
    except ApiError as e:
        return jsonify({"status": "error", "message": str(e), "error_type": _api_error_type(e.status_code)}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "error_type": "unknown"}), 200

    snapshot2_time = datetime.now()
    parsed = parse_all()

    elapsed = (snapshot2_time - state["snapshot1_time"]).total_seconds()
    if elapsed > 0:
        for planet in parsed["planets"]:
            idx = planet["index"]
            health1 = state["snapshot1_health"].get(idx)
            health2 = planet["contest_health"]
            if health1 is not None and health1 > health2 > 0:
                net_rate = (health1 - health2) / elapsed
                planet["liberation_time_hours"] = health2 / net_rate / 3600
            for region in planet.get("regions", []):
                rkey = f"{idx}_r{region['id']}"
                r_h1 = state["snapshot1_health"].get(rkey)
                r_h2 = region["health"]
                if r_h1 is None:
                    continue
                if r_h1 > r_h2 > 0:
                    net_rate = (r_h1 - r_h2) / elapsed
                    region["liberation_time_hours"] = r_h2 / net_rate / 3600
                elif r_h2 > r_h1:
                    net_rate = (r_h2 - r_h1) / elapsed
                    max_h = region.get("max_health", 0)
                    remaining = max_h - r_h2
                    if net_rate > 0 and remaining > 0:
                        region["liberation_time_hours"] = remaining / net_rate / 3600
                        region["region_losing"] = True

    state["last_parsed"] = parsed
    theaters = get_theater_data(parsed, state["flavor"].get("limits", {}), state["classifications"], state["flavor"].get("planet_modifiers", {}))
    modifier_panel = get_modifier_panel_data(parsed, state["flavor"])
    discord_text = format_discord(parsed, state["classifications"], state["flavor"])
    video_text = format_video(parsed, state["classifications"], state["flavor"])
    state["last_outputs"] = {"discord": discord_text, "video": video_text}

    return jsonify({
        "status": "ok",
        "discord": discord_text,
        "video": video_text,
        "theaters": theaters,
        "modifier_panel": modifier_panel,
        "dispatches": parsed.get("dispatches", []),
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
    return jsonify({"status": "ok", "final_tier": value})


@app.route("/save_flavor", methods=["POST"])
def save_flavor():
    data = request.get_json()
    scope = data.get("scope")
    key = data.get("key")
    value = data.get("value", "")
    if scope not in ("theaters", "planets", "planet_notes", "alert_titles") or not key:
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


@app.route("/save_theater_exclude", methods=["POST"])
def save_theater_exclude():
    data = request.get_json()
    faction = data.get("faction")
    excluded = data.get("excluded")
    if not faction or not isinstance(excluded, bool):
        return jsonify({"status": "error", "message": "Invalid request"}), 400
    excl_list = state["flavor"].setdefault("excluded_theaters", [])
    if excluded and faction not in excl_list:
        excl_list.append(faction)
    elif not excluded and faction in excl_list:
        excl_list.remove(faction)
    _save_flavor(state["flavor"])
    return jsonify({"status": "ok"})


@app.route("/ping", methods=["POST"])
def api_ping():
    try:
        ping()
    except ApiError as e:
        return jsonify({"status": "error", "error_type": _api_error_type(e.status_code)})
    return jsonify({"status": "ok"})


@app.route("/save_custom_modifiers", methods=["POST"])
def save_custom_modifiers():
    """Saves the full custom_modifiers list: [{text, tier, planets: [...]}]."""
    data = request.get_json()
    modifiers = data.get("modifiers", [])
    valid = [
        m for m in modifiers
        if isinstance(m, dict) and m.get("text", "").strip()
    ]
    state["flavor"]["custom_modifiers"] = valid
    _save_flavor(state["flavor"])
    return jsonify({"status": "ok"})


@app.route("/save_faction_modifier", methods=["POST"])
def save_faction_modifier():
    """Toggles a single faction modifier key on/off for a planet."""
    data = request.get_json()
    planet = data.get("planet")
    key = data.get("key")
    checked = data.get("checked", False)
    params = data.get("params", {})
    if not planet or not key:
        return jsonify({"status": "error", "message": "Missing planet or key"}), 400
    state["flavor"].setdefault("planet_modifiers", {})
    planet_mods = state["flavor"]["planet_modifiers"].setdefault(planet, {})
    if checked:
        planet_mods[key] = params
    else:
        planet_mods.pop(key, None)
    if not planet_mods:
        state["flavor"]["planet_modifiers"].pop(planet, None)
    _save_flavor(state["flavor"])
    return jsonify({"status": "ok"})


@app.route("/save_free_stratagems", methods=["POST"])
def save_free_stratagems():
    data = request.get_json()
    stratagems = data.get("stratagems", [])
    state["flavor"]["free_stratagems"] = [
        s for s in stratagems if isinstance(s, dict) and s.get("name", "").strip()
    ]
    _save_flavor(state["flavor"])
    return jsonify({"status": "ok"})


@app.route("/reset_modifiers", methods=["POST"])
def reset_modifiers():
    """Clears all faction modifier selections and custom modifiers."""
    state["flavor"]["planet_modifiers"] = {}
    state["flavor"]["custom_modifiers"] = []
    _save_flavor(state["flavor"])
    return jsonify({"status": "ok"})


@app.route("/save_dispatch_selection", methods=["POST"])
def save_dispatch_selection():
    """Toggles a dispatch ID in the selected_dispatches list."""
    data = request.get_json()
    dispatch_id = data.get("id")
    checked = data.get("checked", False)
    if dispatch_id is None:
        return jsonify({"status": "error", "message": "Missing id"}), 400
    selected = state["flavor"].setdefault("selected_dispatches", [])
    if checked and dispatch_id not in selected:
        selected.append(dispatch_id)
    elif not checked and dispatch_id in selected:
        selected.remove(dispatch_id)
    _save_flavor(state["flavor"])
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
