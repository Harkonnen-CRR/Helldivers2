import json
import os
import re
from datetime import datetime, timezone


_TASK_TYPE_MAP = {
    11: "liberate_planet",
    13: "defense_planet",
    12: "control_planet",
    3: "eradicate",
    9: "win_missions",
}

_STATUS_LABEL_MAP = {
    0: "inactive",
    1: "funding",
    2: "active",
    3: "cooldown",
}

# Default broadcast title per API order title. Keyed on the raw `title` field so the
# default is position-independent (a Strategic Threat no longer inherits a Major/Minor
# default just because of its slot). Unknown titles → None → positional fallback in UI.
_ORDER_TITLE_DEFAULTS = {
    "MAJOR ORDER":           "PRIORITY ALERT: NEW MAJOR ORDER",
    "STRATEGIC THREAT":      "PRIORITY ALERT: NEW STRATEGIC THREAT",
    "STRATEGIC OPPORTUNITY": "ALERT: STRATEGIC OPPORTUNITY IDENTIFIED",
}

# Gambit surfacing (flavor/update output): at most ONE gambit per theater — the most
# prominent pull. A gambit needs the community massed on it to be executable, so we only
# surface one when its duo (defending + attacking players) commands at least
# GAMBIT_SHARE_THRESHOLD of that theater's Helldivers; below that, players are too spread
# out to coordinate a pull and we surface none. When two gambits' duos are within
# GAMBIT_DUO_TIE_BAND of each other (as a share of theater pop), they count as "roughly
# equal" and the tie breaks to the larger ATTACKER turnout — the side actually executing
# the pull. (The full multi-gambit list is a future Discord-bot concern, not this output.)
GAMBIT_SHARE_THRESHOLD = 0.40
GAMBIT_DUO_TIE_BAND = 0.10

_EFFECT_LABELS_PATH = os.path.join("fixtures", "effect_labels.json")
_PLANET_EFFECTS_PATH = os.path.join("data", "planet_effects.json")


def _load_effect_labels():
    """Bundled, editable ID→meaning dictionary. Missing/malformed → empty (graceful)."""
    try:
        with open(_EFFECT_LABELS_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _build_effects_by_index():
    """Returns {planet_index: [{id, name, description, known}]} from the cached
    raw-API effects, resolved against the bundled label dictionary. Unknown IDs
    degrade to 'Effect <id>' with known=False. Returns {} if no effects cached
    (raw API never succeeded) — purely additive, never fatal to the core parse."""
    try:
        with open(_PLANET_EFFECTS_PATH) as f:
            cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    labels = _load_effect_labels()
    by_index = {}
    for e in cache.get("effects", []):
        idx = e.get("index")
        eid = e.get("galacticEffectId")
        if idx is None or eid is None:
            continue
        label = labels.get(str(eid))
        if label:
            entry = {"id": eid, "name": label.get("name", f"Effect {eid}"),
                     "description": label.get("description", ""), "known": True}
        else:
            entry = {"id": eid, "name": f"Effect {eid}", "description": "", "known": False}
        by_index.setdefault(idx, []).append(entry)
    return by_index


def _load(filename):
    path = os.path.join("data", filename)
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Required data file not found: {path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed JSON in {path}: {e}")


def _build_planet(planet, campaigns_by_index, effects_by_index=None):
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
        "active_effects": (effects_by_index or {}).get(planet["index"], []),
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
    # API may send reward as null (e.g. Strategic Threats with no medal reward),
    # or a newer rewards[] array. Fall back through both safely.
    reward = a.get("reward") or {}
    if not reward:
        rewards = a.get("rewards") or []
        if rewards:
            reward = rewards[0]
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
        "suggested_title": _ORDER_TITLE_DEFAULTS.get((a.get("title") or "").upper().strip()),
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


def _build_gambits(planets_by_index, campaign_indices):
    """Finds gambit pairs: liberating the enemy-held ATTACKER instantly defends the
    DEFENDER (the planet with an active defense event) if done before its timer expires.
    Returns [{defender, attacker}] (planet indices).

    Robust against the symmetric / supply-line edges that also exist in the attack graph:
    the attacker must be enemy-held with owner matching the defense event's faction AND be
    an active liberation campaign — not merely linked to the defender."""
    gambits = []
    for d_idx, d in planets_by_index.items():
        ev = d.get("event") or {}
        if ev.get("eventType") != 1:
            continue
        atk_faction = ev.get("faction")
        for a_idx, a in planets_by_index.items():
            if a_idx == d_idx:
                continue
            if (d_idx in (a.get("attacking") or [])
                    and a.get("currentOwner") == atk_faction
                    and a_idx in campaign_indices):
                gambits.append({"defender": d_idx, "attacker": a_idx})
    return gambits


def parse_all():
    planets_data = _load("planets.json")
    campaigns_data = _load("campaigns.json")
    assignments_data = _load("assignments.json")
    dss_data = _load("dss.json")
    war_data = _load("war.json")
    dispatches_data = _load("dispatches.json") if os.path.exists(os.path.join("data", "dispatches.json")) else []

    impact_multiplier = war_data["impactMultiplier"]

    campaigns_by_index = {c["planet"]["index"]: c for c in campaigns_data}
    planets_by_index = {p["index"]: p for p in planets_data}
    campaign_indices = set(campaigns_by_index)

    effects_by_index = _build_effects_by_index()
    top_planets = sorted(planets_data, key=lambda p: p["statistics"]["playerCount"], reverse=True)[:5]
    top_indices = {p["index"] for p in top_planets}

    # Every active enemy front contributes its top-by-players planet, so the 3-front
    # guarantee (and "0 = all 3 fronts" mode) always has a candidate even when the global
    # top-5 is one-sided. Front = enemy faction (event faction for defenses, else owner).
    front_tops = {}
    theater_pop = {}  # total players per enemy front — the denominator for gambit share
    for idx in campaign_indices:
        pl = planets_by_index.get(idx)
        if not pl:
            continue
        ev = pl.get("event") or {}
        enemy = ev.get("faction") if ev.get("eventType") == 1 else pl.get("currentOwner")
        if enemy in (None, "Humans"):
            continue
        pc = pl["statistics"]["playerCount"]
        theater_pop[enemy] = theater_pop.get(enemy, 0) + pc
        if enemy not in front_tops or pc > front_tops[enemy][0]:
            front_tops[enemy] = (pc, idx)
    front_indices = [v[1] for v in front_tops.values()]

    # Gambits: one prominent pull per theater, gated on community concentration (see the
    # GAMBIT_* constants). Replaces the old "either side in the global top-5" gate, which
    # surfaced irrelevant pulls whenever a high-turnout DEFENDING planet rode into the top-5.
    def _duo_pop(g):
        return (planets_by_index[g["defender"]]["statistics"]["playerCount"]
                + planets_by_index[g["attacker"]]["statistics"]["playerCount"])

    def _attacker_pop(g):
        return planets_by_index[g["attacker"]]["statistics"]["playerCount"]

    raw_gambits = _build_gambits(planets_by_index, campaign_indices)
    gambits_by_theater = {}
    for g in raw_gambits:
        faction = (planets_by_index[g["defender"]].get("event") or {}).get("faction")
        gambits_by_theater.setdefault(faction, []).append(g)

    gambits = []
    for faction, group in gambits_by_theater.items():
        total = theater_pop.get(faction, 0)
        if not total:
            continue
        lead = max(_duo_pop(g) for g in group)
        # Roughly-equal duos (within the tie band) defer to the larger attacker turnout.
        contenders = [g for g in group if _duo_pop(g) >= lead - GAMBIT_DUO_TIE_BAND * total]
        top = max(contenders, key=_attacker_pop)
        if _duo_pop(top) / total >= GAMBIT_SHARE_THRESHOLD:
            gambits.append(top)
    gambit_by_index = {}
    for g in gambits:
        gambit_by_index[g["defender"]] = {"role": "defender", "partner_index": g["attacker"],
                                          "partner_name": planets_by_index[g["attacker"]]["name"]}
        gambit_by_index[g["attacker"]] = {"role": "attacker", "partner_index": g["defender"],
                                          "partner_name": planets_by_index[g["defender"]]["name"]}

    # Build the top-5 + each front's top planet + gambit partners. dict.fromkeys dedups
    # while keeping top planets in their player-ranked position.
    front_idx_set = set(front_indices)
    gambit_idx_set = {g[k] for g in gambits for k in ("defender", "attacker")}
    build_indices = list(dict.fromkeys(
        [p["index"] for p in top_planets]
        + front_indices
        + [g[k] for g in gambits for k in ("defender", "attacker")]
    ))
    planets = []
    for idx in build_indices:
        pl = _build_planet(planets_by_index[idx], campaigns_by_index, effects_by_index)
        # gambit_added = present ONLY as a gambit partner (not a top-5 nor a front rep),
        # so it does not count toward the display limit — it rides in via gambit closure.
        if idx not in top_indices and idx not in front_idx_set and idx in gambit_idx_set:
            pl["gambit_added"] = True
        if idx in gambit_by_index:
            pl["gambit"] = gambit_by_index[idx]
        planets.append(pl)

    # All-gambits monitor (N2 step4): EVERY raw gambit pair (pre per-theater 40% filter), with
    # built defender/attacker dicts so main.py can attach viability projections without re-reading
    # files. `surfaced` = this pair is the one shown for its theater (in `gambits`). Lets a winnable
    # gambit the display gate filtered out still get flagged on the tracking screen.
    surfaced_keys = {(g["defender"], g["attacker"]) for g in gambits}
    all_gambits = [
        {
            "defender": g["defender"],
            "attacker": g["attacker"],
            "defender_planet": _build_planet(planets_by_index[g["defender"]], campaigns_by_index, effects_by_index),
            "attacker_planet": _build_planet(planets_by_index[g["attacker"]], campaigns_by_index, effects_by_index),
            "faction": (planets_by_index[g["defender"]].get("event") or {}).get("faction"),
            "surfaced": (g["defender"], g["attacker"]) in surfaced_keys,
        }
        for g in raw_gambits
    ]

    return {
        "planets": planets,
        "orders": _build_orders(assignments_data),
        "mo_task_statuses": _build_mo_task_statuses(assignments_data, planets_data, campaigns_by_index),
        "dss": _build_dss(dss_data),
        "dispatches": _build_dispatches(dispatches_data),
        "all_effects_by_index": effects_by_index,  # galaxy-wide, for the effects editor/flag area
        "gambits": gambits,
        "all_gambits": all_gambits,
        "meta": {"impact_multiplier": impact_multiplier},
    }


def build_planet_by_index(index):
    """Build a single planet's reference dict for ANY of the galaxy's planets by index — not
    just the displayed (top/front/gambit) set parse_all() returns. Powers the planet search +
    pin feature. Reuses _build_planet, so a non-campaign planet comes back with its static
    reference (sector/biome/description/regions/owner/players) but no live liberation rate —
    that needs the two-snapshot flow, which only runs for active campaigns."""
    index = int(index)
    planet = next((p for p in _load("planets.json") if p["index"] == index), None)
    if planet is None:
        return None
    campaigns_by_index = {c["planet"]["index"]: c for c in _load("campaigns.json")}
    return _build_planet(planet, campaigns_by_index, _build_effects_by_index())


def list_all_planets():
    """[{index, name}] for every galaxy planet, name-sorted — for the search datalist."""
    return sorted(({"index": p["index"], "name": p["name"]} for p in _load("planets.json")),
                  key=lambda x: x["name"])


def top_populated_indices(n=5):
    """The n most-populated planet indices — the same set the auto-pull seeds the board with.
    Powers the 'Restore top 5' button."""
    planets = sorted(_load("planets.json"), key=lambda p: p["statistics"]["playerCount"], reverse=True)
    return [p["index"] for p in planets[:n]]
