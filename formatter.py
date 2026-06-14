import json
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from status_phrases import get_status_phrase


# Super Earth Standard Time = Arrowhead Game Studios' home timezone (Stockholm).
# The official companion app renders the game's UTC backend in this zone, so we mirror it.
_SEST_ZONE = ZoneInfo("Europe/Stockholm")
_SEST_YEAR_OFFSET = 160  # real year + 160 → in-universe projected year (2026 → 2186)


def _build_sest_stamp(now=None):
    """Star Trek-style SEST timestamp: '{projected_year}.{day_of_year}-{HHMMSS}SEST'.

    Computed live at format time (not parse time) so every output — full, reformat,
    and Quick Update — stamps the actual moment it is generated. Entirely
    Stockholm-derived (date and clock share one timezone), so the day-of-year follows
    SEST and can read 'tomorrow' relative to a US evening. Example: 2186.162-024418SEST
    """
    now = (now or datetime.now(timezone.utc)).astimezone(_SEST_ZONE)
    return f"{now.year + _SEST_YEAR_OFFSET}.{now.strftime('%j')}-{now.strftime('%H%M%S')}SEST"


# type 0 = Medals confirmed; Cape seen in the wild but type number unverified
# TODO: add Cape once we see its type number in live MO data
_REWARD_TYPE_MAP = {
    0: "Medals",
}

_FACTION_MAP = {
    1: "Humans",
    2: "Terminids",
    3: "Automatons",
    4: "Illuminate",
}

_CAMPAIGN_TYPE_MAP = {
    0: "Liberation",
    1: "Recon",
    4: "Defense",
}

_TIER_DISCORD = {
    "large": ("**", "**"),
    "small": ("__", "__"),
    "none":  ("",   ""  ),
}

_TIER_VIDEO_TRANSFORM = {
    "large": str.upper,
    "small": str.title,
    "none":  str.title,
}

_DSS_STATUS_TIER = {
    "active":   "large",
    "funding":  "small",
    "cooldown": "none",
    "inactive": "none",
}

_THEATER_DISPLAY = {
    "Terminids": "TERMINID",
    "Automaton":  "AUTOMATON",
    "Illuminate": "ILLUMINATE",
    "Humans":     "SUPER EARTH CONTROL",
}

_DSS_ITEM_MIX_MAP = {
    3608481516: "Req Slips",
    2985106497: "Rare Samples",
    3992382197: "Common Samples",
}

_FACTION_MODIFIERS = {
    "Terminids": [
        {"key": "predator_strain",   "label": "Predator Strain",   "output": "Predator Strain — rapid and stealthy Terminid variants on-planet",          "params": []},
        {"key": "spore_burst_strain","label": "Spore Burst Strain","output": "Spore Burst Strain — explosive-death Terminid variants present",             "params": []},
        {"key": "rupture_strain",    "label": "Rupture Strain",    "output": "Rupture Strain — burrowing Terminid variants confirmed",                     "params": []},
        {"key": "hive_lords",        "label": "Hive Lords Present","output": "Hive Lords confirmed on-planet",                                             "params": []},
        {"key": "dragonroaches",     "label": "Dragonroaches Active","output": "Dragonroach presence confirmed on-planet",                                  "params": []},
    ],
    "Automaton": [
        {"key": "jet_brigade",       "label": "Jet Brigade",       "output": "Jet Brigade — jetpack-equipped Automaton units active",                      "params": []},
        {"key": "incineration_corps","label": "Incineration Corps","output": "Incineration Corps — flame-based Automaton variants active",                  "params": []},
        {"key": "cyborg_legion",     "label": "Cyborg Legion",     "output": "Cyborg Legion — cybernetically enhanced human fighters present",              "params": []},
        {"key": "hulk_surge",        "label": "Hulk Surge",        "output": "Hulk Surge — increased Hulk-class activity",                                 "params": []},
        {"key": "devastator_surge",  "label": "Devastator Surge",  "output": "Devastator Surge — increased Devastator activity",                           "params": []},
    ],
    "Illuminate": [
        {"key": "appropriators",     "label": "Appropriators",     "output": "Appropriators — piloted walker units and drone variants active",              "params": []},
        {"key": "mindless_masses",   "label": "Mindless Masses",   "output": "Mindless Masses — increased Voteless and Fleshmob spawn rates",              "params": []},
        {"key": "exostorm",          "label": "Exostorm Active",   "output": "Exostorm — Class {class}", "params": [
            {"key": "class", "type": "select", "options": ["1", "2", "3"], "label": "Class"}
        ]},
    ],
}


def _load_planet_index_to_name():
    with open(os.path.join("data", "planets.json")) as f:
        planets = json.load(f)
    return {p["index"]: p["name"] for p in planets}


def _render_task_label(task, planet_index_to_name):
    decoded = task["decoded_type"]
    values = task["values"]
    if decoded in ("liberate_planet", "defense_planet"):
        planet_name = planet_index_to_name.get(values[-1], f"Planet #{values[-1]}")
        verb = "Defend" if decoded == "defense_planet" else "Liberate"
        return f"{verb} {planet_name}"
    if decoded == "eradicate":
        count = values[0]
        faction = _FACTION_MAP.get(values[1], f"Faction {values[1]}")
        return f"Eradicate {count} {faction}"
    if decoded == "win_missions":
        vt = task.get("value_types", [])
        target = next((val for vtype, val in zip(vt, values) if vtype == 3), None)
        faction_id = next((val for vtype, val in zip(vt, values) if vtype == 1), None)
        label = f"Complete {target:,} missions" if target else "Complete missions"
        if faction_id:
            label += f" against {_FACTION_MAP.get(faction_id, f'Faction {faction_id}')}"
        return label
    return f"Unknown objective (raw values: {values})"


def _strip_html(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    text = text.replace(">", "")
    return text.strip()


def _parse_expire(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    # Naive timestamps (e.g. a hand-edited special-event expiry) are assumed UTC so
    # comparisons against datetime.now(timezone.utc) never raise aware/naive TypeErrors.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _time_remaining_hours(expire_str):
    expire = _parse_expire(expire_str)
    if expire is None:
        return None
    return (expire - datetime.now(timezone.utc)).total_seconds() / 3600


def format_duration(hours):
    """Converts float hours to a human-readable duration string.

    Returns 'calculating...' for None, 'imminent' for <= 0, else 'Xd Xhr Ymin'.
    """
    if hours is None:
        return "calculating..."
    if hours <= 0:
        return "imminent"
    total_minutes = int(hours * 60)
    days = total_minutes // (24 * 60)
    remainder = total_minutes % (24 * 60)
    hrs = remainder // 60
    mins = remainder % 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hrs:
        parts.append(f"{hrs}hr")
    if mins or not parts:
        parts.append(f"{mins}min")
    return " ".join(parts)


def _format_lib_time(hours):
    if hours is None:
        return "Establishing a Beachhead"
    return format_duration(hours)


def _format_defense_time(planet):
    """For defense planets: compare measured lib_time to event end.

    Returns (label, value) tuple. label is None for outcome lines (winning/losing)
    so callers emit value as a standalone line with no prefix.
    - lib_time < event_remaining → winning → "Planet Defended in X"
    - lib_time > event_remaining → losing  → "Lost in X"
    - lib_time is None           → unknown → "Time to Defense: Establishing a Beachhead"
    """
    lib_time = planet.get("liberation_time_hours")
    event = planet.get("event") or {}
    event_remaining = _time_remaining_hours(event.get("end_time"))
    if lib_time is None:
        return ("Time to Defense", "Establishing a Beachhead")
    if event_remaining is not None and lib_time > event_remaining:
        return (None, f"Planet Lost in {format_duration(event_remaining)}")
    return (None, f"Planet Defended in {format_duration(lib_time)}")


def _defense_header(planet):
    """Short outcome string for the planet name header on defense planets."""
    lib_time = planet.get("liberation_time_hours")
    event = planet.get("event") or {}
    event_remaining = _time_remaining_hours(event.get("end_time"))
    if lib_time is None:
        return "Establishing a Beachhead"
    if event_remaining is not None and lib_time > event_remaining:
        return f"LOST in {format_duration(event_remaining)}"
    return f"DEFENDED in {format_duration(lib_time)}"


def _format_mo_task_status(status_info, discord=True):
    """Status suffix for a major order objective: SECURE, progress%, or lib/loss time."""
    if not status_info:
        return ""
    t = status_info.get("type")
    if t == "secure":
        return " — **SECURE** ✓" if discord else " — SECURE ✓"
    if t == "progress":
        count = status_info.get("count", 0)
        target = status_info.get("target", 1)
        pct = status_info.get("pct", 0.0)
        if pct >= 100:
            return " — **COMPLETE** ✓" if discord else " — COMPLETE ✓"
        return f" — {count:,} / {target:,} ({pct:.1f}%)"
    if t not in ("liberation", "defense"):
        return ""
    pct = status_info.get("progress_pct", 0.0)
    lib_time = status_info.get("liberation_time_hours")
    if t == "defense":
        event = status_info.get("event") or {}
        event_remaining = _time_remaining_hours(event.get("end_time"))
        if lib_time is not None and event_remaining is not None:
            if lib_time > event_remaining:
                return f" — {pct}% | LOST in {format_duration(event_remaining)}"
            return f" — {pct}% | DEFENDED in {format_duration(lib_time)}"
        return f" — {pct}%"
    if lib_time is not None:
        return f" — {pct}% | LIBERATED in {format_duration(lib_time)}"
    return f" — {pct}%"


def _get_task_status_info(task, task_idx, order, mo_task_statuses, top_planets_by_index):
    """Returns status_info dict for one MO task, or None if unavailable."""
    decoded = task["decoded_type"]
    vt = task.get("value_types", [])
    vals = task.get("values", [])

    if decoded == "win_missions":
        progress_list = order.get("progress") or []
        count = progress_list[task_idx] if task_idx < len(progress_list) else 0
        target = next((v for t, v in zip(vt, vals) if t == 3), None)
        if target and target > 0:
            pct = min(100.0, count / target * 100)
            return {"type": "progress", "count": count, "target": target, "pct": pct}
        return None

    if decoded in ("liberate_planet", "defense_planet"):
        planet_idx = next((v for t, v in zip(vt, vals) if t == 12), None)
        if planet_idx is not None and planet_idx in mo_task_statuses:
            status_info = dict(mo_task_statuses[planet_idx])
            top_p = top_planets_by_index.get(planet_idx)
            if top_p:
                status_info["liberation_time_hours"] = top_p.get("liberation_time_hours")
                status_info["event"] = top_p.get("event")
            return status_info

    return None


def _format_region_status(region):
    if not region.get("players", 0):
        return "Secure"
    health = region.get("health")
    max_health = region.get("max_health", 0)
    pct = (1 - health / max_health) * 100 if (max_health and health is not None) else 0.0
    if pct < 0.1:
        return "Performing recon..."
    if pct <= 3.0:
        return "Establishing a Beachhead"
    lib_time = region.get("liberation_time_hours")
    if lib_time is None:
        return "Calculating..."
    duration = format_duration(lib_time)
    region_type = region.get("size") or "Region"
    if region.get("region_losing"):
        return f"{region_type} Lost in: {duration}"
    return f"{region_type} Secured in: {duration}"


# FUTURE: replace with classify_items_web() for web UI, same input/output shape
def classify_items(parsed_data):
    """Prompts the user to classify each hazard and DSS tactical action as gameplay or flavor.

    Args:
        parsed_data: dict returned by parse_all()
    Returns:
        dict of {key: bool} where True = bold/gameplay, False = italic/flavor
    """
    items = {}

    for planet in parsed_data.get("planets", []):
        for hazard in planet.get("hazards", []):
            if not hazard.get("name") or hazard["name"] == "None":
                continue
            key = f"hazard_{hazard['name']}"
            if key not in items:
                items[key] = {
                    "label": f"Hazard: {hazard['name']}",
                    "description": hazard["description"],
                }

    dss = parsed_data.get("dss")
    if dss:
        for action in dss.get("tactical_actions", []):
            key = f"dss_{action['name']}"
            items[key] = {
                "label": f"DSS Action: {action['name']}",
                "description": _strip_html(action["strategic_description"]),
            }

    classifications = {}
    for key, item in items.items():
        print(f"\n{item['label']}")
        print(f"  {item['description']}")
        while True:
            answer = input("Effect level? (l)arge / (s)mall / (n)one: ").strip().lower()
            if answer in ("l", "large"):
                classifications[key] = "large"
                break
            if answer in ("s", "small"):
                classifications[key] = "small"
                break
            if answer in ("n", "none"):
                classifications[key] = "none"
                break
            print("Please enter l, s, or n.")

    return classifications


def _enemy_faction(planet):
    if planet["is_defense"]:
        return planet["event"]["faction"]
    return planet["current_owner"]


_DEFAULT_ORDER_TITLES = [
    "PRIORITY ALERT: NEW MAJOR ORDER",
    "PRIORITY ALERT: NEW MINOR ORDER",
    "ALERT: STRATEGIC OPPORTUNITY IDENTIFIED",
]


def _get_order_title(order, index, flavor):
    """Returns the user-selected title for an order, falling back to suggested then position-based default."""
    labels = flavor.get("order_labels") or {}
    saved = labels.get(str(order["id"]))
    if saved:
        return saved
    if order.get("suggested_title"):
        return order["suggested_title"]
    if index < len(_DEFAULT_ORDER_TITLES):
        return _DEFAULT_ORDER_TITLES[index]
    return "ALERT: ORDER UPDATE"


def _order_visible(order, flavor):
    """Returns True unless the user has explicitly hidden this order."""
    visibility = flavor.get("order_visibility") or {}
    return visibility.get(str(order["id"]), True)


def _get_mo_planet_indices(parsed_data):
    """Planet indices an MO targets — drives the ★ marker and MO-first sort.

    Reads the value-type-12 (planet index) slot from EVERY MO task, not just
    liberate/defense: win_missions / control_planet / eradicate tasks also carry their
    target planet there. E.g. a "complete N missions" Major Order scoped to Omicron stores
    Omicron's index in type-12 even though the task type isn't planet-named."""
    indices = set()
    for order in parsed_data.get("orders", []):
        for task in order.get("tasks", []):
            for vtype, val in zip(task["value_types"], task["values"]):
                if vtype == 12:  # value type 12 = planet index in HD2 API
                    indices.add(val)
    return indices


def _get_mo_target_faction(parsed_data):
    for order in parsed_data.get("orders", []):
        for task in order.get("tasks", []):
            if task["decoded_type"] == "eradicate":
                for vtype, val in zip(task["value_types"], task["values"]):
                    if vtype == 1:  # value type 1 = faction/race index
                        return val
    return None


def _planet_sort_key(planet, mo_indices, mo_target_faction, has_unknown_task):
    in_mo = planet["index"] in mo_indices
    if has_unknown_task:
        # FUTURE: plug in correct task type value when identified
        return (0 if in_mo else 1, -planet["player_count"])
    is_target = mo_target_faction and _enemy_faction(planet) == mo_target_faction
    return (0 if in_mo else 1, 0 if is_target else 1, -planet["player_count"])


def _hidden_planet_indices(flavor_texts):
    """Planet indices the user has toggled OFF via the per-planet show/hide control.
    Stored as planet_visibility = {str(index): bool}, default-shown; hidden = value is False."""
    vis = flavor_texts.get("planet_visibility", {})
    return {int(idx) for idx, shown in vis.items() if not shown}


def _build_theaters(parsed_data, hidden_indices=None):
    """Groups planets by enemy faction. Theater order = first appearance in parsed_data['planets'].

    Within each theater, planets are sorted: MO planets first, then non-MO, both by player count desc.
    Pass hidden_indices (a set of planet indices) to drop user-hidden planets up front — done
    here, before any limit/balance, so a hidden planet frees its slot rather than consuming it.
    A faction whose planets are all hidden simply never appears (empty front auto-dropped).
    Returns (theater_order list, theaters dict).
    """
    orders = parsed_data.get("orders", [])
    mo_indices = _get_mo_planet_indices(parsed_data)
    mo_target_faction = _get_mo_target_faction(parsed_data)
    has_unknown_task = any(
        t["decoded_type"].startswith("unknown_type_")
        for order in orders
        for t in order.get("tasks", [])
    )

    hidden_indices = hidden_indices or set()
    theater_order = []
    theaters = {}
    for planet in parsed_data["planets"]:
        if planet.get("gambit_added"):
            continue  # display attachment only — added by gambit closure, not the limit
        if planet["index"] in hidden_indices:
            continue  # per-planet hide — dropped before limit/balance so it frees a slot
        faction = _enemy_faction(planet)
        if faction not in theaters:
            theaters[faction] = []
            theater_order.append(faction)
        theaters[faction].append(planet)

    for faction in theater_order:
        theaters[faction].sort(
            key=lambda p: _planet_sort_key(p, mo_indices, mo_target_faction, has_unknown_task)
        )

    return theater_order, theaters


def _apply_board_order(theater_order, theaters, theater_seq, planet_seq):
    """Apply the user's manual board arrangement on top of the default ordering: reorder the
    fronts by theater_seq (list of factions) and the planets within each front by planet_seq
    (list of planet indices). Items the user hasn't moved keep their default (stable) order.
    BOTH the editor (get_theater_data) and the output (format_discord/video) call this, so the
    broadcast reflects the on-screen arrangement."""
    if theater_seq:
        trank = {f: i for i, f in enumerate(theater_seq)}
        theater_order = sorted(theater_order, key=lambda f: trank.get(f, len(trank)))
    if planet_seq:
        prank = {idx: i for i, idx in enumerate(planet_seq)}
        for faction in list(theaters):
            theaters[faction] = sorted(theaters[faction],
                                       key=lambda p: prank.get(p["index"], len(prank)))
    return theater_order, theaters


def _balance_theaters(theater_order, theaters, parsed_data, global_limit, excluded):
    """Applies a global planet cap with a 3-front guarantee.

    Selects at most global_limit planets total across all non-excluded factions.
    Every non-excluded faction that has any planets is guaranteed at least one slot.
    When a faction would be dropped, the lowest-priority planet from the most
    over-represented faction is swapped out in its favour.
    Returns a new (theater_order, theaters) pair.
    """
    if not global_limit or global_limit <= 0:
        return theater_order, theaters

    orders = parsed_data.get("orders", [])
    mo_indices = _get_mo_planet_indices(parsed_data)
    mo_target_faction = _get_mo_target_faction(parsed_data)
    has_unknown_task = any(
        t["decoded_type"].startswith("unknown_type_")
        for order in orders
        for t in order.get("tasks", [])
    )

    def sort_key(planet):
        return _planet_sort_key(planet, mo_indices, mo_target_faction, has_unknown_task)

    active = [f for f in theater_order if f not in excluded]

    # Flatten all active planets globally, sorted by priority
    all_tagged = []
    for faction in active:
        for planet in theaters.get(faction, []):
            all_tagged.append((faction, planet))
    all_tagged.sort(key=lambda fp: sort_key(fp[1]))

    if not all_tagged:
        return theater_order, theaters

    selected = list(all_tagged[:global_limit])

    # Guarantee each active faction with planets has at least one slot
    for faction in active:
        if any(f == faction for f, _ in selected):
            continue

        # Best available planet from this faction not already selected
        sel_indices = {p["index"] for _, p in selected}
        available = [p for f, p in all_tagged if f == faction and p["index"] not in sel_indices]
        if not available:
            continue

        # Swap out the worst-priority planet from a faction holding >1 slot
        counts = {}
        for f, _ in selected:
            counts[f] = counts.get(f, 0) + 1
        over = {f for f, c in counts.items() if c > 1}
        if not over:
            continue

        candidates = [(i, p) for i, (f, p) in enumerate(selected) if f in over]
        candidates.sort(key=lambda ip: sort_key(ip[1]), reverse=True)
        selected[candidates[0][0]] = (faction, available[0])

    # Rebuild theater structures preserving original faction order
    new_theaters = {}
    for faction, planet in selected:
        new_theaters.setdefault(faction, []).append(planet)
    for faction in new_theaters:
        new_theaters[faction].sort(key=sort_key)
    new_order = [f for f in theater_order if f in new_theaters]

    return new_order, new_theaters


def _gambit_summaries(parsed_data):
    """One entry per gambit — {faction, defender, attacker} planet dicts — for the per-theater
    GAMBITS block. faction = the shared enemy front of the pair."""
    by_index = {p["index"]: p for p in parsed_data.get("planets", [])}
    out = []
    for g in parsed_data.get("gambits", []):
        d = by_index.get(g["defender"])
        a = by_index.get(g["attacker"])
        if d and a:
            out.append({"faction": _enemy_faction(d), "defender": d, "attacker": a,
                        "projection": g.get("projection")})
    return out


def get_gambit_monitor_data(parsed_data):
    """N2 step4 tracking screen: a display row per RAW gambit pair (every possible gambit in the
    galaxy, not just the prominent one per theater the update shows). Winnable pulls — current
    Helldivers on pace — sort first and carry winnable=True so the UI can flag them, including
    ones the per-theater display gate filtered out. Populated from parsed['gambit_monitor']
    (projections attached in main.fetch2); empty until the two-snapshot has run."""
    out = []
    for m in parsed_data.get("gambit_monitor", []):
        v = (m.get("projection") or {}).get("viability") or {}
        out.append({
            "defender_name": m["defender_name"],
            "attacker_name": m["attacker_name"],
            "defender_players": m.get("defender_players") or 0,
            "attacker_players": m.get("attacker_players") or 0,
            "faction": m.get("faction"),
            "surfaced": bool(m.get("surfaced")),
            "winnable": bool(v.get("winnable")),
            "status": v.get("status"),
            "viability": _gambit_viability_line(m.get("projection"), m["defender_name"], m["attacker_name"]),
        })
    # Winnable-now first, then by attacker turnout (the pull most likely to coordinate).
    out.sort(key=lambda x: (not x["winnable"], -x["attacker_players"]))
    return out


def _gambit_viability_line(projection, defender_name, attacker_name):
    """Readable one-line verdict for a gambit's viability projection ('' if none yet)."""
    if not projection:
        return ""
    v = projection.get("viability") or {}
    status = v.get("status")
    if status == "window_closed":
        return "⚑ Defense window has closed"
    if status == "stalled":
        return "⚠ Progress stalled — more reinforcements urgently needed"
    if status != "ok":
        return "⚑ Viability: awaiting field data"
    if v.get("winnable"):
        return "✓ WINNABLE — current Helldivers are on pace to take it in time"
    add = round(v.get("additional_needed", 0))
    line = f"✗ Not winnable — needs ~{add:,} more Helldivers on {attacker_name} to win in time"
    if v.get("mobilizable"):
        line += f" (within reach if {defender_name} mobilizes)"
    return line


def _gambit_defender_status(d):
    label, value = _format_defense_time(d)
    return f"{label}: {value}" if label else value


def _gambit_attacker_status(a):
    lib = a.get("liberation_time_hours")
    return f"Liberation in {format_duration(lib)}" if lib is not None else "Establishing a Beachhead"


def _gambit_block_discord(faction, summaries):
    rows = [s for s in summaries if s["faction"] == faction]
    if not rows:
        return []
    lines = ["**⚔ GAMBITS**"]
    for s in rows:
        d, a = s["defender"], s["attacker"]
        lines.append(f"> **Defending:** {d['name']} — {d['player_count']:,} players — {_gambit_defender_status(d)}")
        lines.append(f"> **Attacking:** {a['name']} — {a['player_count']:,} players — {_gambit_attacker_status(a)}")
        vline = _gambit_viability_line(s.get("projection"), d["name"], a["name"])
        if vline:
            lines.append(f"> {vline}")
        lines.append("")
    return lines


def _gambit_block_video(faction, summaries):
    rows = [s for s in summaries if s["faction"] == faction]
    if not rows:
        return []
    lines = ["GAMBITS"]
    for s in rows:
        d, a = s["defender"], s["attacker"]
        lines.append(f"  DEFENDING: {d['name'].upper()} — {d['player_count']:,} players — {_gambit_defender_status(d)}")
        lines.append(f"  ATTACKING: {a['name'].upper()} — {a['player_count']:,} players — {_gambit_attacker_status(a)}")
        vline = _gambit_viability_line(s.get("projection"), d["name"], a["name"])
        if vline:
            lines.append(f"  {vline}")
        lines.append("")
    return lines


def _format_hazard_discord(hazard, classifications):
    key = f"hazard_{hazard['name']}"
    tier = classifications.get(key, "none")
    prefix, suffix = _TIER_DISCORD.get(tier, ("", ""))
    return f"{prefix}{hazard['name']}{suffix} — *{hazard['description']}*"


def _format_hazard_video(hazard, classifications):
    key = f"hazard_{hazard['name']}"
    tier = classifications.get(key, "none")
    transform = _TIER_VIDEO_TRANSFORM.get(tier, str.title)
    return f"{transform(hazard['name'])} — {hazard['description']}"


def _dss_cost_label(action):
    """Returns the resource type label (e.g. 'Req Slips') for a DSS action, or empty string."""
    fps = action.get("funding_progress", [])
    if fps:
        item_id = fps[0].get("item_mix_id")
        return _DSS_ITEM_MIX_MAP.get(item_id, "")
    return ""


def _dss_status_phrase(action):
    """Returns the status + timing phrase for a DSS tactical action."""
    status = action["status_label"]
    expire = action.get("status_expire")
    fps = action.get("funding_progress", [])

    if status == "funding":
        phrase = "Accruing Donations"
        if fps:
            fp = fps[0]
            remaining_units = fp["target"] - fp["current"]
            if fp["delta_per_second"] > 0:
                eta = format_duration((remaining_units / fp["delta_per_second"]) / 3600)
                phrase += f", Ready in {eta}"
        return phrase
    if status == "active":
        phrase = "Active"
        if expire:
            hrs = _time_remaining_hours(expire)
            if hrs and hrs > 0:
                phrase += f", Active for {format_duration(hrs)}"
        return phrase
    if status == "cooldown":
        phrase = "On Cooldown"
        if expire:
            hrs = _time_remaining_hours(expire)
            if hrs and hrs > 0:
                phrase += f", Available for donations in {format_duration(hrs)}"
        return phrase
    return status.title()


def _format_dss_discord(dss):
    """Returns a list of Discord-formatted lines for the DSS section."""
    lines = []
    lines.append("**DSS UPDATE**")
    ftl_str = ""
    if dss.get("election_end"):
        hrs = _time_remaining_hours(dss["election_end"])
        if hrs and hrs > 0:
            ftl_str = f" ({format_duration(hrs)} until FTL jump)"
    lines.append(f"**Location:** {dss['planet_name']}{ftl_str}")
    lines.append("")
    for action in dss["tactical_actions"]:
        cost = _dss_cost_label(action)
        cost_str = f" ({cost})" if cost else ""
        phrase = _dss_status_phrase(action)
        desc = _strip_html(action["strategic_description"])
        lines.append(f"**{action['name']}**{cost_str} — {phrase}")
        if desc:
            lines.append(f"│ *{desc}*")
    return lines


def _format_dss_video(dss):
    """Returns a list of plain-text lines for the DSS section."""
    lines = []
    lines.append("DSS UPDATE")
    ftl_str = ""
    if dss.get("election_end"):
        hrs = _time_remaining_hours(dss["election_end"])
        if hrs and hrs > 0:
            ftl_str = f" ({format_duration(hrs)} until FTL jump)"
    lines.append(f"Location: {dss['planet_name']}{ftl_str}")
    lines.append("")
    for action in dss["tactical_actions"]:
        cost = _dss_cost_label(action)
        cost_str = f" ({cost})" if cost else ""
        phrase = _dss_status_phrase(action)
        desc = _strip_html(action["strategic_description"])
        lines.append(f"{action['name']}{cost_str} — {phrase}")
        if desc:
            lines.append(f"  {desc}")
    return lines


def _dss_attached_discord(dss):
    """Full DSS detail rendered UNDER its orbiting planet's block (Discord quote style)."""
    lines = ["> **⊙ DSS IN ORBIT**"]
    if dss.get("election_end"):
        hrs = _time_remaining_hours(dss["election_end"])
        if hrs and hrs > 0:
            lines.append(f"> *{format_duration(hrs)} until FTL jump*")
    for action in dss["tactical_actions"]:
        cost = _dss_cost_label(action)
        cost_str = f" ({cost})" if cost else ""
        phrase = _dss_status_phrase(action)
        lines.append(f"> **{action['name']}**{cost_str} — {phrase}")
        desc = _strip_html(action["strategic_description"])
        if desc:
            lines.append(f"> │ *{desc}*")
    return lines


def _dss_attached_video(dss):
    """Full DSS detail rendered UNDER its orbiting planet's block (plain-text/indented)."""
    lines = ["    ⊙ DSS IN ORBIT"]
    if dss.get("election_end"):
        hrs = _time_remaining_hours(dss["election_end"])
        if hrs and hrs > 0:
            lines.append(f"    {format_duration(hrs)} until FTL jump")
    for action in dss["tactical_actions"]:
        cost = _dss_cost_label(action)
        cost_str = f" ({cost})" if cost else ""
        phrase = _dss_status_phrase(action)
        lines.append(f"    {action['name']}{cost_str} — {phrase}")
        desc = _strip_html(action["strategic_description"])
        if desc:
            lines.append(f"      {desc}")
    return lines


MAJOR_SEP = "================================================"
MINOR_SEP = "------------------------------------------------"

# Output sections in canonical render order. To add a new section: append its
# key here, add a label in SECTION_LABELS, and write _section_<key>_discord and
# _section_<key>_video helpers. Everything else (full output, quick update,
# future Discord bot) picks it up automatically.
SECTION_KEYS = ["orders", "fleetwide", "intel", "planets", "dss"]
SECTION_LABELS = {
    "orders": "Orders",
    "fleetwide": "Fleetwide Equipment",
    "intel": "Recent Intel",
    "planets": "Planet Report",
    "dss": "DSS Status",
}


def get_output_sections():
    """Returns the ordered section list (key + label) for UI/bot consumption."""
    return [{"key": k, "label": SECTION_LABELS[k]} for k in SECTION_KEYS]


def _ordered_sections(flavor_texts):
    """SECTION_KEYS reordered by the user's on-the-fly section_order (stable; unlisted keys
    keep their default position). Lets the whole broadcast be re-typeset — sections moved
    up/down — and the output reflects it."""
    seq = (flavor_texts or {}).get("section_order") or []
    rank = {k: i for i, k in enumerate(seq) if k in SECTION_LABELS}
    return sorted(SECTION_KEYS, key=lambda k: rank.get(k, len(rank)))


def _effect_display(effect, effect_formats):
    """Returns (name, description) to show for an effect, or None to skip.
    Custom format text replaces the name and drops the description (the user's
    phrasing is the whole line). Default = community name + description.
    Unlabeled unknowns never render."""
    fmt = (effect_formats or {}).get(str(effect["id"]))
    if fmt is not None:
        if not fmt.get("enabled", True):
            return None
        text = (fmt.get("text") or "").strip()
        if text:
            return (text, "")
        # empty custom text + enabled → fall through to default
    if effect.get("known"):
        return (effect["name"], (effect.get("description") or "").strip())
    return None


def _dedup_effects(effects):
    """Collapses effects that share an identical description — the API's paired
    '(Enemies)' duplicates (e.g. 1307 'HIVE LORDS (Enemies)' + 1308 'HIVE LORDS').
    Keeps one per description, preferring the name without a parenthetical.
    Effects with no description (unlabeled unknowns) pass through untouched."""
    order = []
    by_desc = {}
    for e in effects:
        d = (e.get("description") or "").strip().lower()
        if not d:
            order.append(e)
            continue
        if d not in by_desc:
            by_desc[d] = e
            order.append(e)
        elif "(" in by_desc[d]["name"] and "(" not in e["name"]:
            order[order.index(by_desc[d])] = e  # prefer the clean name
            by_desc[d] = e
    return order


# ── Discord section renderers — each returns a list of lines (empty if N/A) ──

def _section_orders_discord(parsed_data, flavor_texts):
    orders = parsed_data.get("orders", [])
    visible_orders = [o for o in orders if _order_visible(o, flavor_texts)]
    manual_orders = [m for m in (flavor_texts.get("manual_orders") or []) if m.get("title", "").strip()]
    if not (visible_orders or manual_orders):
        return []
    planet_index_to_name = _load_planet_index_to_name()
    top_planets_by_index = {p["index"]: p for p in parsed_data.get("planets", [])}
    mo_task_statuses = parsed_data.get("mo_task_statuses", {})

    lines = []
    for i, order in enumerate(visible_orders):
        reward_label = _REWARD_TYPE_MAP.get(order["reward_type"], "Medals")
        title = _get_order_title(order, i, flavor_texts)
        lines.append(f"**{title}**")
        lines.append(f"> {order['briefing']}")
        if order.get("description"):
            lines.append(f"> {order['description']}")
        if order.get("reward_amount") is not None:
            lines.append(f"> **Reward:** {order['reward_amount']} {reward_label}")
        lines.append(f"> **Expires in:** {format_duration(_time_remaining_hours(order['expiration']))}")
        lines.append("> **Objectives:**")
        for task_idx, task in enumerate(order["tasks"]):
            status_info = _get_task_status_info(task, task_idx, order, mo_task_statuses, top_planets_by_index)
            lines.append(f">   • {_render_task_label(task, planet_index_to_name)}{_format_mo_task_status(status_info, discord=True)}")
        lines.append("")
    for m in manual_orders:
        lines.append(f"**{m['title'].strip()}**")
        lines.append("")
    return lines


def _timed_item_active(item, parsed_data):
    """Shared active-gate for special events AND fleetwide equipment: shown iff enabled,
    not past its expiry, and — if linked to an order — that order is still in the current
    feed (so it auto-hides the moment the MO completes/disappears). Expiry and order-link
    are independent gates: set either, both, or neither."""
    if not item.get("enabled", True):
        return False
    expires = item.get("expires")
    if expires:
        remaining = _time_remaining_hours(expires)
        if remaining is not None and remaining <= 0:
            return False
    linked = item.get("linked_order_id")
    if linked:
        order_ids = {str(o.get("id")) for o in parsed_data.get("orders", [])}
        if str(linked) not in order_ids:
            return False
    return True


def _event_entries(event):
    """Normalizes a special event's modifier list into [{text, tier}] entries, coercing
    legacy plain-string lines to tier 'none' and dropping empties."""
    out = []
    for ln in (event.get("lines") or []):
        if isinstance(ln, str):
            text, tier = ln.strip(), "none"
        elif isinstance(ln, dict):
            text = (ln.get("text") or "").strip()
            tier = ln.get("tier") if ln.get("tier") in _TIER_DISCORD else "none"
        else:
            continue
        if text:
            out.append({"text": text, "tier": tier})
    return out


def _active_special_events(flavor_texts, parsed_data, scope):
    """Active special events for a given scope ('all' or 'planets'), in order, skipping
    empty bundles (no name and no entries)."""
    out = []
    for e in (flavor_texts.get("special_events") or []):
        if e.get("scope", "all") != scope:
            continue
        has_content = (e.get("name") or "").strip() or bool(_event_entries(e))
        if has_content and _timed_item_active(e, parsed_data):
            out.append(e)
    return out


def _detected_equipment(parsed_data):
    """Fleetwide equipment grants AUTO-DETECTED from live galactic effects named
    'ARSENAL AUGMENTATION: <equipment>'. Reliable structured names; the effect's presence IS
    the timer (auto-appears when granted, auto-vanishes when it ends — no expiry to track).
    Returns [{name, detected: True}], deduped, in stable order."""
    seen = {}
    for effs in (parsed_data.get("all_effects_by_index") or {}).values():
        for e in effs:
            name = (e.get("name") or "")
            if name.upper().startswith("ARSENAL AUGMENTATION:"):
                equip = name.split(":", 1)[1].strip()
                if equip:
                    seen.setdefault(equip.upper(), {"name": equip, "detected": True})
    return list(seen.values())


def _active_equipment(flavor_texts, parsed_data, scope):
    """Active fleetwide-equipment items for a scope ('all'|'planets'), in order. For the
    fleetwide ('all') scope, live AUTO-DETECTED ARSENAL AUGMENTATION grants are merged in,
    deduped against manual entries (manual takes precedence on a name clash)."""
    out = []
    manual_names = set()
    for s in (flavor_texts.get("free_stratagems") or []):
        if not (s.get("name") or "").strip():
            continue
        if s.get("scope", "all") != scope:
            continue
        if _timed_item_active(s, parsed_data):
            out.append(s)
            manual_names.add(s["name"].strip().upper())
    if scope == "all":
        for d in _detected_equipment(parsed_data):
            if d["name"].upper() not in manual_names:
                out.append(d)
    return out


def _section_fleetwide_discord(parsed_data, flavor_texts):
    events = _active_special_events(flavor_texts, parsed_data, "all")
    equipment = _active_equipment(flavor_texts, parsed_data, "all")
    if not (events or equipment):
        return []
    lines = []
    if events:
        lines.append("**FLEETWIDE STATUS**")
        for e in events:
            if e.get("name", "").strip():
                lines.append(f"> **{e['name'].strip()}**")
            for entry in _event_entries(e):
                pre, suf = _TIER_DISCORD.get(entry["tier"], ("", ""))
                lines.append(f">   • {pre}{entry['text']}{suf}")
        lines.append("")
    if equipment:
        lines.append("**FLEETWIDE EQUIPMENT**")
        for s in equipment:
            lines.append(f"> **{s['name'].strip()}**")
        lines.append("")
    return lines


def _section_intel_discord(parsed_data, flavor_texts):
    selected_ids = set(flavor_texts.get("selected_dispatches") or [])
    selected_dispatches = [d for d in (parsed_data.get("dispatches") or []) if d["id"] in selected_ids]
    if not selected_dispatches:
        return []
    lines = ["**RECENT INTEL**"]
    for d in selected_dispatches:
        age = d.get("age_label", "")
        title = d.get("title", "")
        body = d.get("body", "")
        header = f"{title}  |  {age}" if age else title
        lines.append(f"> **{header}**")
        if body:
            for bline in body.splitlines():
                if bline.strip():
                    lines.append(f"> {bline.strip()}")
    lines.append("")
    return lines


def _section_planets_discord(parsed_data, classifications, flavor_texts):
    special_planet_events = _active_special_events(flavor_texts, parsed_data, "planets")
    special_fleetwide_events = _active_special_events(flavor_texts, parsed_data, "all")
    equipment_planet = _active_equipment(flavor_texts, parsed_data, "planets")
    gambit_summaries = _gambit_summaries(parsed_data)
    theater_flavors = flavor_texts.get("theaters", {})
    planet_flavors = flavor_texts.get("planets", {})
    dss = parsed_data.get("dss")
    dss_planet_index = dss["planet_index"] if dss else None

    theater_order, theaters = _build_theaters(parsed_data, _hidden_planet_indices(flavor_texts))
    excluded = set(flavor_texts.get("excluded_theaters", []))
    global_limit = int(flavor_texts.get("global_planet_limit") or 0)
    if global_limit > 0:
        theater_order, theaters = _balance_theaters(theater_order, theaters, parsed_data, global_limit, excluded)
    theater_order = [f for f in theater_order if f not in excluded]
    theater_order, theaters = _apply_board_order(
        theater_order, theaters, flavor_texts.get("theater_order"), flavor_texts.get("planet_order"))

    lines = []
    for i, faction in enumerate(theater_order):
        if i > 0:
            lines.append("---")
        display = _THEATER_DISPLAY.get(faction, faction.upper())
        lines.append(f"**{display}{'' if faction == 'Humans' else ' FRONT'}**")
        theater_text = theater_flavors.get(faction)
        if theater_text:
            lines.append(f"*{theater_text}*")
        lines.append("")
        lines.extend(_gambit_block_discord(faction, gambit_summaries))

        for planet in theaters[faction]:
            is_def = planet["is_defense"]
            on_dss = planet["index"] == dss_planet_index

            if is_def:
                outcome = _defense_header(planet)
            else:
                lib_time = planet.get("liberation_time_hours")
                outcome = f"LIBERATED in {format_duration(lib_time)}" if lib_time is not None else "Establishing a Beachhead"
            pct = planet["progress_pct"]
            phrase = get_status_phrase("defense" if is_def else "liberation", pct)
            header = f"{pct}% — {phrase}" if pct is not None else phrase
            # keep the time/secure outcome only when it adds info beyond the generic phrase
            if outcome and outcome != "Establishing a Beachhead":
                header += f" · {outcome}"
            lines.append(f"**{planet['name']}: {header}**")

            planet_text = planet_flavors.get(planet["name"])
            if planet_text:
                lines.append(f"*{planet_text}*")
            lines.append("")

            planet_mods = (flavor_texts.get("planet_modifiers") or {}).get(planet["name"], {})
            enemy_faction = _enemy_faction(planet)

            if is_def:
                count_label = "Invasion Level"
            elif planet_mods.get("exostorm"):
                count_label = "Campaign Level"
            else:
                count_label = "Enemy Resistance"

            lines.append("__**Planetary Details and Modifiers**__")

            if on_dss and dss:
                lines.extend(_dss_attached_discord(dss))

            lines.append(f"> Sector: {planet['sector']} | Biome: **{planet['biome']}**")
            hp_max = planet.get("contest_max_health", 0)
            if hp_max:
                lines.append(f"> Current HP: {int(planet['contest_health']):,}/{int(hp_max):,}")
            lines.append(f"> Players: {planet['player_count']:,}")
            if count_label == "Enemy Resistance":
                max_h = planet.get("contest_max_health", 0)
                regen = planet.get("regen_per_second", 0)
                if max_h and regen:
                    resistance = round(regen * 3600 / max_h * 100, 2)
                    lines.append(f"> **Enemy Resistance: {resistance}%**")
            elif planet.get("campaign_level") is not None:
                lines.append(f"> **{count_label}: {planet['campaign_level']}**")
            for mod in _FACTION_MODIFIERS.get(enemy_faction, []):
                if mod["key"] in planet_mods:
                    params = planet_mods[mod["key"]]
                    try:
                        output = mod["output"].format(**params) if params else mod["output"]
                    except KeyError:
                        output = mod["output"]
                    lines.append(f"> **{output}**")

            for eff in _dedup_effects(planet.get("active_effects", [])):
                disp = _effect_display(eff, flavor_texts.get("effect_formats"))
                if disp:
                    name, desc = disp
                    lines.append(f"> **{name}** — *{desc}*" if desc else f"> **{name}**")

            hazards = [h for h in planet.get("hazards", []) if h.get("name") and h["name"] != "None"]
            for hazard in hazards:
                lines.append(f"> {_format_hazard_discord(hazard, classifications)}")

            for cm in (flavor_texts.get("custom_modifiers") or []):
                if planet["name"] in cm.get("planets", []) and cm.get("text", "").strip():
                    pre, suf = _TIER_DISCORD.get(cm.get("tier", "none"), ("", ""))
                    lines.append(f"> {pre}{cm['text'].strip()}{suf}")

            for e in special_planet_events:
                if planet["name"] in (e.get("planets") or []):
                    if e.get("name", "").strip():
                        lines.append(f"> **{e['name'].strip()}**")
                    for entry in _event_entries(e):
                        pre, suf = _TIER_DISCORD.get(entry["tier"], ("", ""))
                        lines.append(f">   • {pre}{entry['text']}{suf}")
            for e in special_fleetwide_events:
                if e.get("name", "").strip():
                    lines.append(f"> **{e['name'].strip()}** *(fleetwide)*")
            for s in equipment_planet:
                if planet["name"] in (s.get("planets") or []):
                    lines.append(f"> **{s['name'].strip()}** *(equipment)*")

            active_regions = [r for r in planet.get("regions", []) if r.get("players", 0) > 0 and r["health"] < r["max_health"]]
            if active_regions:
                lines.append("")
                lines.append("__**Population Centers:**__")
                for r in active_regions:
                    pct = round((1 - r["health"] / r["max_health"]) * 100, 1) if (r["max_health"] and r["health"] is not None) else 0.0
                    size = f"{r['size']} — " if r.get("size") else ""
                    status = _format_region_status(r)
                    status_str = f"**{status}**" if ("Secured in" in status or "Lost in" in status) else status
                    phrase = get_status_phrase("region", pct)
                    lines.append(f"> **{r['name'].upper()}** ({size}{r['players']} Helldivers) — {pct}% cleared — {phrase} | {status_str}")

            lines.append("")
    return lines


def _displayed_planet_indices(parsed_data, flavor_texts):
    """The set of planet indices the Planet Report actually renders (after hide + 3-front
    balance/limit + exclude; board pins/removes are already baked into parsed['planets'])."""
    theater_order, theaters = _build_theaters(parsed_data, _hidden_planet_indices(flavor_texts))
    excluded = set(flavor_texts.get("excluded_theaters", []))
    global_limit = int(flavor_texts.get("global_planet_limit") or 0)
    if global_limit > 0:
        theater_order, theaters = _balance_theaters(theater_order, theaters, parsed_data, global_limit, excluded)
    theater_order = [f for f in theater_order if f not in excluded]
    return {p["index"] for f in theater_order for p in theaters[f]}


def _section_dss_discord(parsed_data, flavor_texts):
    dss = parsed_data.get("dss")
    if not dss:
        return []
    # When the DSS's planet is on the board, the DSS is shown attached to it — skip the
    # standalone block. Only render here as a fallback when that planet isn't displayed.
    if dss.get("planet_index") in _displayed_planet_indices(parsed_data, flavor_texts):
        return []
    return ["", *_format_dss_discord(dss)]


def format_discord(parsed_data, classifications, flavor_texts=None, sections=None):
    """Formats parsed war data as Discord markdown.

    Args:
        parsed_data: dict from parse_all()
        classifications: dict from classify_items()
        flavor_texts: optional dict with "theaters" and "planets" sub-dicts
        sections: optional list of section keys to include; default = all in canonical order
    Returns:
        str of Discord markdown
    """
    flavor_texts = flavor_texts or {}
    sections = SECTION_KEYS if sections is None else sections
    renderers = {
        "orders":    lambda: _section_orders_discord(parsed_data, flavor_texts),
        "fleetwide": lambda: _section_fleetwide_discord(parsed_data, flavor_texts),
        "intel":     lambda: _section_intel_discord(parsed_data, flavor_texts),
        "planets":   lambda: _section_planets_discord(parsed_data, classifications, flavor_texts),
        "dss":       lambda: _section_dss_discord(parsed_data, flavor_texts),
    }
    lines = [f"**Galactic War Update: {_build_sest_stamp()}**", ""]
    for key in _ordered_sections(flavor_texts):
        if key in sections:
            lines.extend(renderers[key]())
    return "\n".join(lines)


# ── Video section renderers — each returns a list of lines (empty if N/A) ──

def _section_orders_video(parsed_data, flavor_texts):
    orders = parsed_data.get("orders", [])
    visible_orders = [o for o in orders if _order_visible(o, flavor_texts)]
    manual_orders = [m for m in (flavor_texts.get("manual_orders") or []) if m.get("title", "").strip()]
    if not (visible_orders or manual_orders):
        return []
    planet_index_to_name = _load_planet_index_to_name()
    top_planets_by_index = {p["index"]: p for p in parsed_data.get("planets", [])}
    mo_task_statuses = parsed_data.get("mo_task_statuses", {})

    lines = []
    for i, order in enumerate(visible_orders):
        reward_label = _REWARD_TYPE_MAP.get(order["reward_type"], "Medals")
        title = _get_order_title(order, i, flavor_texts)
        lines.append(title)
        lines.append(MINOR_SEP)
        lines.append(f"    {order['briefing']}")
        if order.get("description"):
            lines.append(f"    {order['description']}")
        if order.get("reward_amount") is not None:
            lines.append(f"    Reward: {order['reward_amount']} {reward_label}")
        lines.append(f"    Expires in: {format_duration(_time_remaining_hours(order['expiration']))}")
        lines.append("    Objectives:")
        for task_idx, task in enumerate(order["tasks"]):
            status_info = _get_task_status_info(task, task_idx, order, mo_task_statuses, top_planets_by_index)
            lines.append(f"      - {_render_task_label(task, planet_index_to_name)}{_format_mo_task_status(status_info, discord=False)}")
        lines.append("")
    for m in manual_orders:
        lines.append(m["title"].strip())
        lines.append(MINOR_SEP)
        lines.append("")
    return lines


def _section_fleetwide_video(parsed_data, flavor_texts):
    events = _active_special_events(flavor_texts, parsed_data, "all")
    equipment = _active_equipment(flavor_texts, parsed_data, "all")
    if not (events or equipment):
        return []
    lines = []
    if events:
        lines += [MAJOR_SEP, "FLEETWIDE STATUS", MAJOR_SEP]
        for e in events:
            if e.get("name", "").strip():
                lines.append(f"  {e['name'].strip().upper()}")
            for entry in _event_entries(e):
                transform = _TIER_VIDEO_TRANSFORM.get(entry["tier"], str.title)
                lines.append(f"    {transform(entry['text'])}")
        lines.append("")
    if equipment:
        lines += [MAJOR_SEP, "FLEETWIDE EQUIPMENT", MAJOR_SEP]
        for s in equipment:
            lines.append(f"  {s['name'].strip().upper()}")
        lines.append("")
    return lines


def _section_intel_video(parsed_data, flavor_texts):
    selected_ids = set(flavor_texts.get("selected_dispatches") or [])
    selected_dispatches = [d for d in (parsed_data.get("dispatches") or []) if d["id"] in selected_ids]
    if not selected_dispatches:
        return []
    lines = [MAJOR_SEP, "RECENT INTEL", MAJOR_SEP]
    for d in selected_dispatches:
        age = d.get("age_label", "")
        title = d.get("title", "")
        body = d.get("body", "")
        lines.append(f"  [{age}] {title}" if age else f"  {title}")
        if body:
            for bline in body.splitlines():
                if bline.strip():
                    lines.append(f"    {bline.strip()}")
        lines.append("")
    return lines


def _section_planets_video(parsed_data, classifications, flavor_texts):
    special_planet_events = _active_special_events(flavor_texts, parsed_data, "planets")
    special_fleetwide_events = _active_special_events(flavor_texts, parsed_data, "all")
    equipment_planet = _active_equipment(flavor_texts, parsed_data, "planets")
    gambit_summaries = _gambit_summaries(parsed_data)
    theater_flavors = flavor_texts.get("theaters", {})
    planet_flavors = flavor_texts.get("planets", {})
    dss = parsed_data.get("dss")
    dss_planet_index = dss["planet_index"] if dss else None

    theater_order, theaters = _build_theaters(parsed_data, _hidden_planet_indices(flavor_texts))
    excluded = set(flavor_texts.get("excluded_theaters", []))
    global_limit = int(flavor_texts.get("global_planet_limit") or 0)
    if global_limit > 0:
        theater_order, theaters = _balance_theaters(theater_order, theaters, parsed_data, global_limit, excluded)
    theater_order = [f for f in theater_order if f not in excluded]
    theater_order, theaters = _apply_board_order(
        theater_order, theaters, flavor_texts.get("theater_order"), flavor_texts.get("planet_order"))

    lines = []
    for faction in theater_order:
        lines.append(MAJOR_SEP)
        display = _THEATER_DISPLAY.get(faction, faction.upper())
        lines.append(f"{display}{'' if faction == 'Humans' else ' FRONT'}")
        lines.append(MAJOR_SEP)
        theater_text = theater_flavors.get(faction)
        if theater_text:
            lines.append(theater_text)
        lines.append("")
        lines.extend(_gambit_block_video(faction, gambit_summaries))

        for planet in theaters[faction]:
            is_def = planet["is_defense"]
            on_dss = planet["index"] == dss_planet_index
            dss_tag = " (DSS IN ORBIT)" if on_dss else ""

            lines.append(MINOR_SEP)
            lines.append(f"{planet['name'].upper()}{dss_tag}")
            lines.append(MINOR_SEP)

            if on_dss and dss:
                lines.extend(_dss_attached_video(dss))

            planet_text = planet_flavors.get(planet["name"])
            if planet_text:
                lines.append(f"    {planet_text}")
                lines.append("")

            progress_label = "Defense Progress" if is_def else "Liberation Progress"

            planet_mods = (flavor_texts.get("planet_modifiers") or {}).get(planet["name"], {})
            enemy_faction = _enemy_faction(planet)
            for mod in _FACTION_MODIFIERS.get(enemy_faction, []):
                if mod["key"] in planet_mods:
                    params = planet_mods[mod["key"]]
                    try:
                        output = mod["output"].format(**params) if params else mod["output"]
                    except KeyError:
                        output = mod["output"]
                    lines.append(f"    {output}")

            for eff in _dedup_effects(planet.get("active_effects", [])):
                disp = _effect_display(eff, flavor_texts.get("effect_formats"))
                if disp:
                    name, desc = disp
                    lines.append(f"    {name} — {desc}" if desc else f"    {name}")

            lines.append(f"    Sector: {planet['sector']} | Biome: {planet['biome']}")
            campaign_type_label = _CAMPAIGN_TYPE_MAP.get(planet['campaign_type'], f"Unknown ({planet['campaign_type']})")
            lines.append(f"    Campaign Level: {planet['campaign_level']} | Type: {campaign_type_label}")
            lines.append(f"    Players: {planet['player_count']:,}")
            planet_phrase = get_status_phrase("defense" if is_def else "liberation", planet["progress_pct"])
            lines.append(f"    {progress_label}: {planet['progress_pct']}% — {planet_phrase}")
            if is_def:
                d_label, d_time = _format_defense_time(planet)
                if d_label:
                    lines.append(f"    {d_label}: {d_time}")
                else:
                    lines.append(f"    {d_time}")
            else:
                lib_str = _format_lib_time(planet["liberation_time_hours"])
                if planet["liberation_time_hours"] is not None:
                    lines.append(f"    LIBERATED in: {lib_str}")
                else:
                    lines.append(f"    {lib_str}")
            lines.append(f"    Regen/sec: {planet['regen_per_second']:.2f}")

            hazards = [h for h in planet.get("hazards", []) if h.get("name") and h["name"] != "None"]
            if hazards:
                lines.append("    Hazards:")
                for hazard in hazards:
                    lines.append(f"      {_format_hazard_video(hazard, classifications)}")

            for cm in (flavor_texts.get("custom_modifiers") or []):
                if planet["name"] in cm.get("planets", []) and cm.get("text", "").strip():
                    transform = _TIER_VIDEO_TRANSFORM.get(cm.get("tier", "none"), str.title)
                    lines.append(f"    {transform(cm['text'].strip())}")

            for e in special_planet_events:
                if planet["name"] in (e.get("planets") or []):
                    if e.get("name", "").strip():
                        lines.append(f"    {e['name'].strip().upper()}")
                    for entry in _event_entries(e):
                        transform = _TIER_VIDEO_TRANSFORM.get(entry["tier"], str.title)
                        lines.append(f"      {transform(entry['text'])}")
            for e in special_fleetwide_events:
                if e.get("name", "").strip():
                    lines.append(f"    {e['name'].strip().upper()} (FLEETWIDE)")
            for s in equipment_planet:
                if planet["name"] in (s.get("planets") or []):
                    lines.append(f"    {s['name'].strip().upper()} (EQUIPMENT)")

            active_regions = [r for r in planet.get("regions", []) if r.get("players", 0) > 0 and r["health"] < r["max_health"]]
            if active_regions:
                lines.append("    Population Centers:")
                for r in active_regions:
                    pct = round((1 - r["health"] / r["max_health"]) * 100, 1) if (r["max_health"] and r["health"] is not None) else 0.0
                    size = f"{r['size']} — " if r.get("size") else ""
                    status = _format_region_status(r)
                    phrase = get_status_phrase("region", pct)
                    lines.append(f"      {r['name'].upper()} ({size}{r['players']} Helldivers) — {pct}% cleared — {phrase} | {status}")

            lines.append("")
    return lines


def _section_dss_video(parsed_data, flavor_texts):
    dss = parsed_data.get("dss")
    if not dss:
        return []
    if dss.get("planet_index") in _displayed_planet_indices(parsed_data, flavor_texts):
        return []  # shown attached to its planet
    return [MAJOR_SEP, *_format_dss_video(dss)]


def format_video(parsed_data, classifications, flavor_texts=None, sections=None):
    """Formats parsed war data as plain text for video scripts.

    Args:
        parsed_data: dict from parse_all()
        classifications: dict from classify_items()
        flavor_texts: optional dict with "theaters" and "planets" sub-dicts
        sections: optional list of section keys to include; default = all in canonical order
    Returns:
        str of plain text with no markdown
    """
    flavor_texts = flavor_texts or {}
    sections = SECTION_KEYS if sections is None else sections
    lines = [MAJOR_SEP, f"GALACTIC WAR UPDATE: {_build_sest_stamp()}", MAJOR_SEP, ""]
    renderers = {
        "orders":    lambda: _section_orders_video(parsed_data, flavor_texts),
        "fleetwide": lambda: _section_fleetwide_video(parsed_data, flavor_texts),
        "intel":     lambda: _section_intel_video(parsed_data, flavor_texts),
        "planets":   lambda: _section_planets_video(parsed_data, classifications, flavor_texts),
        "dss":       lambda: _section_dss_video(parsed_data, flavor_texts),
    }
    for key in _ordered_sections(flavor_texts):
        if key in sections:
            lines.extend(renderers[key]())
    return "\n".join(lines)


def _dss_action_timing(action):
    status = action["status_label"]
    if status in ("cooldown", "active") and action.get("status_expire"):
        label = "Ready in" if status == "cooldown" else "Active for"
        return f"{label}: {format_duration(_time_remaining_hours(action['status_expire']))}"
    if status == "funding":
        fps = action.get("funding_progress", [])
        if fps:
            fp = fps[0]
            remaining = fp["target"] - fp["current"]
            if fp["delta_per_second"] > 0:
                eta = format_duration((remaining / fp["delta_per_second"]) / 3600)
                pct = round((fp["current"] / fp["target"]) * 100, 1)
                return f"{pct}% funded | ETA: {eta}"
    return None


def get_dss_ref(parsed_data):
    """The DSS reference block (orbiting planet + tactical actions), or None — independent of
    which planets are displayed, so the editor can attach it to its planet's card when shown OR
    fall back to a standalone DSS panel when that planet is off the board."""
    dss = parsed_data.get("dss")
    if not dss:
        return None
    ftl = format_duration(_time_remaining_hours(dss["election_end"])) if dss.get("election_end") else None
    return {
        "planet_index": dss["planet_index"],
        "planet_name": dss["planet_name"],
        "ftl_jump": ftl,
        "actions": [
            {"name": a["name"], "status": a["status_label"], "cost_label": _dss_cost_label(a),
             "phrase": _dss_status_phrase(a), "description": _strip_html(a["strategic_description"])}
            for a in dss["tactical_actions"]
        ],
    }


def get_theater_data(parsed_data, classifications=None, planet_modifiers=None,
                     planet_visibility=None, theater_seq=None, planet_seq=None):
    """Returns structured theater data for the flavor editor reference panels.

    Pre-formats all durations and task labels so the JS template has no calculation to do.
    Returns a list of theater dicts, one per faction, in display order.

    Every planet is returned (no hide-filtering here) and tagged with its `visible` state so
    the editor can render a per-planet show/hide toggle, including for hidden planets.
    """
    classifications = classifications or {}
    planet_modifiers = planet_modifiers or {}
    planet_visibility = planet_visibility or {}
    theater_order, theaters = _build_theaters(parsed_data)
    theater_order, theaters = _apply_board_order(theater_order, theaters, theater_seq, planet_seq)
    orders = parsed_data.get("orders", [])
    dss = parsed_data.get("dss")
    mo_indices = _get_mo_planet_indices(parsed_data)
    gambit_summaries = _gambit_summaries(parsed_data)

    mo_task_labels = []
    if orders:
        planet_index_to_name = _load_planet_index_to_name()
        for order in orders:
            mo_task_labels.extend([_render_task_label(t, planet_index_to_name) for t in order.get("tasks", [])])

    result = []
    for faction in theater_order:
        planets = theaters[faction]
        mo_relevant = any(p["index"] in mo_indices for p in planets)
        dss_in_theater = dss and any(p["index"] == dss["planet_index"] for p in planets)

        planet_refs = []
        for p in planets:
            hazards = [
                {
                    "name": h["name"],
                    "description": h.get("description", ""),
                    "key": f"hazard_{h['name']}",
                    "tier": classifications.get(f"hazard_{h['name']}", "none"),
                }
                for h in p.get("hazards", []) if h.get("name") and h["name"] != "None"
            ]
            enemy_faction = _enemy_faction(p)
            modifier_options = _FACTION_MODIFIERS.get(enemy_faction, [])
            if p["is_defense"]:
                d_label, d_time = _format_defense_time(p)
                time_status = f"{d_label}: {d_time}" if d_label else d_time
            else:
                lib_str = _format_lib_time(p["liberation_time_hours"])
                time_status = f"Time to Liberation: {lib_str}" if p["liberation_time_hours"] is not None else lib_str
            regions = []
            for r in p.get("regions", []):
                pct = round((1 - r["health"] / r["max_health"]) * 100, 1) if (r["max_health"] and r["health"] is not None) else 0.0
                regions.append({
                    "name": r["name"],
                    "size": r.get("size", ""),
                    "players": r["players"],
                    "progress_pct": pct,
                    "is_available": r["is_available"],
                    "status": _format_region_status(r),
                    "status_phrase": get_status_phrase("region", pct),
                })
            planet_refs.append({
                "index": p["index"],
                "visible": planet_visibility.get(str(p["index"]), True),
                "name": p["name"],
                "player_count": f"{p['player_count']:,}",
                "progress_pct": p["progress_pct"],
                "status_phrase": get_status_phrase("defense" if p["is_defense"] else "liberation", p["progress_pct"]),
                "time_status": time_status,
                "is_defense": p["is_defense"],
                "is_mo": p["index"] in mo_indices,
                "sector": p.get("sector", ""),
                "biome": p.get("biome", ""),
                "biome_description": p.get("biome_description", ""),
                "hazards": hazards,
                "regions": regions,
                "modifier_options": modifier_options,
                "active_modifiers": planet_modifiers.get(p["name"], {}),
            })

        mo_ref = None
        if orders and mo_relevant:
            first_order = orders[0]
            reward_label = _REWARD_TYPE_MAP.get(first_order["reward_type"], "Medals")
            mo_ref = {
                "briefing": first_order["briefing"],
                "reward": f"{first_order['reward_amount']} {reward_label}",
                "expires": format_duration(_time_remaining_hours(first_order["expiration"])),
                "tasks": mo_task_labels,
            }

        dss_ref = get_dss_ref(parsed_data) if dss_in_theater else None

        theater_gambits = []
        for s in gambit_summaries:
            if s["faction"] != faction:
                continue
            d, a = s["defender"], s["attacker"]
            theater_gambits.append({
                "defender_name": d["name"],
                "defender_players": f"{d['player_count']:,}",
                "defender_status": _gambit_defender_status(d),
                "attacker_name": a["name"],
                "attacker_players": f"{a['player_count']:,}",
                "attacker_status": _gambit_attacker_status(a),
                "viability": _gambit_viability_line(s.get("projection"), d["name"], a["name"]),
            })

        result.append({
            "faction": faction,
            "planets": planet_refs,
            "mo": mo_ref,
            "dss": dss_ref,
            "gambits": theater_gambits,
        })

    return result


def get_effects_panel_data(parsed_data, flavor):
    """Galaxy-wide effects for the formatting editor + unknown flag area.
    Distinct effects across ALL planets (not just shown), split known/unknown,
    each with its current format state and the planets carrying it."""
    formats = (flavor or {}).get("effect_formats", {})
    effects_by_index = parsed_data.get("all_effects_by_index", {})
    try:
        with open(os.path.join("data", "planets.json")) as f:
            meta = {p["index"]: {"name": p["name"], "owner": p["currentOwner"]} for p in json.load(f)}
    except (FileNotFoundError, json.JSONDecodeError):
        meta = {}

    seen = {}
    for idx, effects in effects_by_index.items():
        pname = meta.get(idx, {}).get("name", f"#{idx}")
        powner = meta.get(idx, {}).get("owner", "")
        for e in effects:
            eid = e["id"]
            entry = seen.get(eid)
            if not entry:
                fmt = formats.get(str(eid), {})
                entry = {
                    "id": eid, "name": e["name"], "description": e.get("description", ""),
                    "known": e["known"], "planets": [],
                    "text": fmt.get("text", ""), "enabled": fmt.get("enabled", True),
                }
                seen[eid] = entry
            if pname not in entry["planets"]:
                entry["planets"].append(pname)
                entry.setdefault("owners", set()).add(powner)

    out = []
    for e in sorted(seen.values(), key=lambda x: x["id"]):
        e["owners"] = sorted(o for o in e.pop("owners", set()) if o)
        out.append(e)
    return {
        "known": [e for e in out if e["known"]],
        "unknown": [e for e in out if not e["known"]],
    }


def get_modifier_panel_data(parsed_data, flavor):
    """Returns data for the consolidated Gameplay Modifiers panel.

    Builds the Special Factions rows (faction modifier × applicable planets)
    and passes through custom_modifiers with the active planet list.
    """
    planet_modifiers = flavor.get("planet_modifiers", {})

    theater_order, theaters = _build_theaters(parsed_data)

    # Ordered list of active planets with their enemy faction
    active_planets = []
    for faction in theater_order:
        for planet in theaters[faction]:
            active_planets.append({
                "name": planet["name"],
                "faction": _enemy_faction(planet),
            })

    # One row per faction modifier; only include if ≥1 active planet matches
    faction_rows = []
    for faction, modifiers in _FACTION_MODIFIERS.items():
        applicable = [p for p in active_planets if p["faction"] == faction]
        if not applicable:
            continue
        for mod in modifiers:
            planet_checks = []
            for p in applicable:
                saved = planet_modifiers.get(p["name"], {})
                planet_checks.append({
                    "name": p["name"],
                    "checked": mod["key"] in saved,
                    "params": saved.get(mod["key"], {}),
                })
            faction_rows.append({
                "key": mod["key"],
                "label": mod["label"],
                "faction": faction,
                "params": mod["params"],
                "planets": planet_checks,
            })

    return {
        "faction_rows": faction_rows,
        "active_planets": active_planets,
        "custom_modifiers": flavor.get("custom_modifiers", []),
    }


def save_outputs(discord_text, video_text):
    """Saves Discord and video outputs to the output/ directory.

    Args:
        discord_text: str of Discord markdown
        video_text: str of plain text video script
    """
    os.makedirs("output", exist_ok=True)
    discord_path = "output/discord_post.txt"
    video_path = "output/video_script.txt"
    with open(discord_path, "w") as f:
        f.write(discord_text)
    with open(video_path, "w") as f:
        f.write(video_text)
    print(f"Saved Discord post to {discord_path}")
    print(f"Saved video script to {video_path}")


def format_all(parsed_data, classifications, flavor_texts=None):
    """Produces both Discord and video text outputs from parsed war data.

    Args:
        parsed_data: dict from parse_all()
        classifications: dict from classify_items()
        flavor_texts: optional dict with "theaters" and "planets" sub-dicts
    Returns:
        tuple of (discord_text, video_text)
    """
    return (
        format_discord(parsed_data, classifications, flavor_texts),
        format_video(parsed_data, classifications, flavor_texts),
    )


if __name__ == "__main__":
    from data_parser import parse_all
    parsed = parse_all()
    classifications = classify_items(parsed)
    discord_text = format_discord(parsed, classifications)
    video_text = format_video(parsed, classifications)
    save_outputs(discord_text, video_text)
    print(discord_text)
