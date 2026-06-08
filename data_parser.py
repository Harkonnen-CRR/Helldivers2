import json
import os
import re
from datetime import datetime, timezone


_TASK_TYPE_MAP = {
    11: "liberate_planet",
    13: "defense_planet",
    12: "control_planet",
    3: "eradicate",
}

_STATUS_LABEL_MAP = {
    0: "inactive",
    1: "funding",
    2: "active",
    3: "cooldown",
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


def _build_planet(planet, campaigns_by_index):
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

    is_defense = raw_event is not None and raw_event.get("eventType") == 1
    contest_health = raw_event["health"] if is_defense else health
    contest_max_health = raw_event["maxHealth"] if is_defense else max_health

    progress_pct = round((1 - contest_health / contest_max_health) * 100, 2) if contest_max_health else None

    regions = []
    for r in planet.get("regions", []):
        desc = r.get("description", "")
        if desc == "null":
            desc = ""
        regions.append({
            "id": r["id"],
            "name": r["name"],
            "size": r.get("size", ""),
            "description": desc,
            "health": r["health"],
            "max_health": r["maxHealth"],
            "regen_per_second": r.get("regenPerSecond", 0),
            "availability_factor": r.get("availabilityFactor", 0),
            "is_available": r.get("isAvailable", False),
            "players": r.get("players", 0),
            "liberation_time_hours": None,
            "region_losing": False,
        })

    return {
        "index": planet["index"],
        "name": planet["name"],
        "sector": planet["sector"],
        "current_owner": planet["currentOwner"],
        "player_count": player_count,
        "biome": planet["biome"]["name"],
        "biome_description": planet["biome"].get("description", ""),
        "hazards": [{"name": h["name"], "description": h["description"]} for h in planet.get("hazards", [])],
        "regions": regions,
        "progress_pct": progress_pct,
        "is_defense": is_defense,
        "contest_health": contest_health,
        "contest_max_health": contest_max_health,
        "regen_per_second": planet["regenPerSecond"],
        "liberation_time_hours": None,
        "campaign_level": campaign["count"] if campaign else None,
        "campaign_type": campaign["type"] if campaign else None,
        "event": event,
    }


def _build_mo_task_statuses(assignments, planets_data, campaigns_by_index):
    """Returns {planet_index: {type, progress_pct}} for planet-linked tasks across all orders."""
    if not assignments:
        return {}
    planet_by_index = {p["index"]: p for p in planets_data}
    statuses = {}

    for a in assignments:
        progress = a.get("progress") or []
        for i, t in enumerate(a.get("tasks", [])):
            decoded = _TASK_TYPE_MAP.get(t["type"], "")
            if decoded not in ("liberate_planet", "defense_planet"):
                continue

            planet_idx = None
            for vtype, val in zip(t.get("valueTypes", []), t.get("values", [])):
                if vtype == 12:
                    planet_idx = val
                    break
            if planet_idx is None:
                continue

            task_progress = progress[i] if i < len(progress) else None
            if task_progress is not None and task_progress >= 1:
                statuses[planet_idx] = {"type": "secure"}
                continue

            planet = planet_by_index.get(planet_idx)
            if not planet:
                continue

            campaign = campaigns_by_index.get(planet_idx)
            event = planet.get("event")
            is_defense = event is not None and event.get("eventType") == 1

            if planet.get("currentOwner") == "Humans" and not campaign:
                statuses[planet_idx] = {"type": "secure"}
            elif is_defense:
                health = event["health"]
                max_health = event["maxHealth"]
                pct = round((1 - health / max_health) * 100, 2) if max_health else 0.0
                statuses[planet_idx] = {"type": "defense", "progress_pct": pct}
            elif campaign:
                health = planet["health"]
                max_health = planet["maxHealth"]
                pct = round((1 - health / max_health) * 100, 2) if max_health else 0.0
                statuses[planet_idx] = {"type": "liberation", "progress_pct": pct}
            else:
                statuses[planet_idx] = {"type": "not_started"}

    return statuses


def _build_order(a):
    """Builds a single order dict from one assignment entry."""
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


def _build_orders(assignments):
    """Returns a list of order dicts, one per assignment."""
    return [_build_order(a) for a in assignments] if assignments else []


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
                    "item_mix_id": c.get("itemMixId"),
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


def _strip_dispatch_tags(text):
    """Remove HD2 inline formatting tags like <i=1>, <br>, etc."""
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _dispatch_age_label(published_str, now):
    """Returns 'Today', 'Yesterday', 'X days ago' relative to now (UTC date comparison)."""
    try:
        published = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return ""
    delta = (now.date() - published.astimezone(timezone.utc).date()).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Yesterday"
    return f"{delta} days ago"


def _build_dispatches(dispatches_data):
    """Returns dispatches published within the last 7 days, most recent first."""
    if not dispatches_data:
        return []
    now = datetime.now(timezone.utc)
    results = []
    for d in dispatches_data:
        published_str = d.get("published", "")
        try:
            published = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if (now - published).days > 7:
            continue
        clean = _strip_dispatch_tags(d.get("message", ""))
        lines = [l.strip() for l in clean.splitlines() if l.strip()]
        title = lines[0] if lines else ""
        body = "\n".join(lines[1:]) if len(lines) > 1 else ""
        results.append({
            "id": d["id"],
            "published": published_str,
            "age_label": _dispatch_age_label(published_str, now),
            "title": title,
            "body": body,
        })
    results.sort(key=lambda x: x["published"], reverse=True)
    return results


def parse_all():
    planets_data = _load("planets.json")
    campaigns_data = _load("campaigns.json")
    assignments_data = _load("assignments.json")
    dss_data = _load("dss.json")
    war_data = _load("war.json")
    dispatches_data = _load("dispatches.json") if os.path.exists(os.path.join("data", "dispatches.json")) else []

    impact_multiplier = war_data["impactMultiplier"]

    campaigns_by_index = {c["planet"]["index"]: c for c in campaigns_data}

    top_planets = sorted(planets_data, key=lambda p: p["statistics"]["playerCount"], reverse=True)[:5]
    planets = [_build_planet(p, campaigns_by_index) for p in top_planets]

    return {
        "planets": planets,
        "orders": _build_orders(assignments_data),
        "mo_task_statuses": _build_mo_task_statuses(assignments_data, planets_data, campaigns_by_index),
        "dss": _build_dss(dss_data),
        "dispatches": _build_dispatches(dispatches_data),
        "meta": {"impact_multiplier": impact_multiplier},
    }
