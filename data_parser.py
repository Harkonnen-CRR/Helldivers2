import json
import os


_TASK_TYPE_MAP = {
    11: "liberate_planet",
    13: "defense_planet",
    12: "control_planet",
    3: "eradicate",
}

_STATUS_LABEL_MAP = {
    3: "cooldown",
    1: "funding",
    0: "inactive",
    2: "unknown_2",
}


def _load(filename):
    path = os.path.join("data", filename)
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Required data file not found: {path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed JSON in {path}: {e}")


def _liberation_time(health, player_count, regen_per_second, impact_multiplier):
    net = impact_multiplier * player_count - regen_per_second
    if net <= 0:
        return None
    return (health / net) / 3600


def _build_planet(planet, campaigns_by_index, impact_multiplier, exostorm):  # EXOSTORM — remove this block if mechanic is retired
    stats = planet["statistics"]
    player_count = stats["playerCount"]
    health = planet["health"]
    max_health = planet["maxHealth"]

    campaign = campaigns_by_index.get(planet["index"])

    raw_event = planet.get("event")
    if raw_event:
        event = {
            "event_type": raw_event["eventType"],
            "faction": raw_event["faction"],
            "health": raw_event["health"],
            "max_health": raw_event["maxHealth"],
            "start_time": raw_event["startTime"],
            "end_time": raw_event["endTime"],
            "campaign_id": raw_event["campaignId"],
        }
    else:
        event = None

    is_defense = raw_event is not None
    contest_health = raw_event["health"] if is_defense else health
    contest_max_health = raw_event["maxHealth"] if is_defense else max_health

    progress_pct = round((1 - contest_health / contest_max_health) * 100, 2) if contest_max_health else None
    lib_time = None if is_defense else _liberation_time(contest_health, player_count, planet["regenPerSecond"], impact_multiplier)  # Defense planets require two fetches to calculate net rate — handled at dashboard layer

    return {
        "index": planet["index"],
        "name": planet["name"],
        "sector": planet["sector"],
        "current_owner": planet["currentOwner"],
        "player_count": player_count,
        "biome": planet["biome"]["name"],
        "hazards": [{"name": h["name"], "description": h["description"]} for h in planet.get("hazards", [])],
        "progress_pct": progress_pct,
        "is_defense": is_defense,
        "regen_per_second": planet["regenPerSecond"],
        "liberation_time_hours": lib_time,
        "campaign_level": campaign["count"] if campaign else None,
        "campaign_type": campaign["type"] if campaign else None,
        "event": event,
        "exostorm": exostorm if exostorm and planet["name"] == exostorm.get("planet") else None,  # EXOSTORM — remove this block if mechanic is retired
    }


def _build_major_order(assignments):
    if not assignments:
        return None
    a = assignments[0]
    reward = a.get("reward", {})
    tasks = []
    for t in a.get("tasks", []):
        task_type = t["type"]
        tasks.append({
            "type": task_type,
            "values": t["values"],
            "value_types": t["valueTypes"],
            "decoded_type": _TASK_TYPE_MAP.get(task_type, f"unknown_type_{task_type}"),
        })
    return {
        "id": a["id"],
        "title": a["title"],
        "briefing": a["briefing"],
        "description": a["description"],
        "reward_type": reward.get("type"),
        "reward_amount": reward.get("amount"),
        "expiration": a["expiration"],
        "tasks": tasks,
        "progress": a.get("progress"),
    }


def _build_dss(dss_data):
    if not dss_data:
        return None
    item = dss_data[0]
    planet = item["planet"]
    actions = []
    for ta in item.get("tacticalActions", []):
        status = ta["status"]
        actions.append({
            "name": ta["name"],
            "strategic_description": ta["strategicDescription"],
            "status": status,
            "status_label": _STATUS_LABEL_MAP.get(status, f"unknown_{status}"),
            "status_expire": ta.get("statusExpire"),
            "funding_progress": [
                {
                    "current": c["currentValue"],
                    "target": c["targetValue"],
                    "delta_per_second": c["deltaPerSecond"],
                }
                for c in ta.get("costs", [])
            ],
        })
    return {
        "planet_name": planet["name"],
        "planet_index": planet["index"],
        "election_end": item.get("electionEnd"),
        "tactical_actions": actions,
    }


def parse_all(exostorm=None):  # EXOSTORM — remove this block if mechanic is retired
    planets_data = _load("planets.json")
    campaigns_data = _load("campaigns.json")
    assignments_data = _load("assignments.json")
    dss_data = _load("dss.json")
    war_data = _load("war.json")

    impact_multiplier = war_data["impactMultiplier"]

    campaigns_by_index = {c["planet"]["index"]: c for c in campaigns_data}

    top_planets = sorted(planets_data, key=lambda p: p["statistics"]["playerCount"], reverse=True)[:5]
    planets = [_build_planet(p, campaigns_by_index, impact_multiplier, exostorm) for p in top_planets]  # EXOSTORM — remove this block if mechanic is retired

    return {
        "planets": planets,
        "major_order": _build_major_order(assignments_data),
        "dss": _build_dss(dss_data),
        "meta": {
            "impact_multiplier": impact_multiplier,
            "exostorm_input": exostorm,  # EXOSTORM — remove this block if mechanic is retired
        },
    }
