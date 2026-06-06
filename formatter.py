import json
import os
import re
from datetime import datetime, timezone


_REWARD_TYPE_MAP = {
    0: "Medals",
    1: "Super Credits",
    2: "Requisition Slips",
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
    "Humans":     "HUMAN",
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
    return f"Unknown objective (raw values: {values})"


def _strip_html(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    text = text.replace(">", "")
    return text.strip()


def _parse_expire(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


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


def _format_region_status(region):
    if not region.get("players", 0):
        return "Secure"
    health = region.get("health", 0)
    max_health = region.get("max_health", 0)
    pct = (1 - health / max_health) * 100 if max_health else 0.0
    if pct < 0.1:
        return "Performing recon..."
    if pct <= 3.0:
        return "Establishing a Beachhead"
    lib_time = region.get("liberation_time_hours")
    if lib_time is None:
        return "Calculating..."
    duration = format_duration(lib_time)
    if region.get("region_losing"):
        return f"Region Lost in: {duration}"
    return f"Region Secured in: {duration}"


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


def _get_mo_planet_indices(parsed_data):
    mo = parsed_data.get("major_order")
    if not mo:
        return set()
    indices = set()
    for task in mo.get("tasks", []):
        if task["decoded_type"] in ("liberate_planet", "defense_planet"):
            for vtype, val in zip(task["value_types"], task["values"]):
                if vtype == 12:  # value type 12 = planet index in HD2 API
                    indices.add(val)
    return indices


def _get_mo_target_faction(parsed_data):
    mo = parsed_data.get("major_order")
    if not mo:
        return None
    for task in mo.get("tasks", []):
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


def _build_theaters(parsed_data):
    """Groups planets by enemy faction. Theater order = first appearance in parsed_data['planets'].

    Within each theater, planets are sorted: MO planets first, then non-MO, both by player count desc.
    Returns (theater_order list, theaters dict).
    """
    mo = parsed_data.get("major_order")
    mo_indices = _get_mo_planet_indices(parsed_data)
    mo_target_faction = _get_mo_target_faction(parsed_data)
    has_unknown_task = mo and any(
        t["decoded_type"].startswith("unknown_type_") for t in mo.get("tasks", [])
    )

    theater_order = []
    theaters = {}
    for planet in parsed_data["planets"]:
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


def format_discord(parsed_data, classifications, flavor_texts=None):
    """Formats parsed war data as Discord markdown.

    Args:
        parsed_data: dict from parse_all()
        classifications: dict from classify_items()
        flavor_texts: optional dict with "theaters" and "planets" sub-dicts
    Returns:
        str of Discord markdown with character count footer
    """
    flavor_texts = flavor_texts or {}
    theater_flavors = flavor_texts.get("theaters", {})
    planet_flavors = flavor_texts.get("planets", {})

    lines = []
    mo = parsed_data.get("major_order")
    dss = parsed_data.get("dss")
    dss_planet_index = dss["planet_index"] if dss else None

    if mo:
        planet_index_to_name = _load_planet_index_to_name()
        reward_label = _REWARD_TYPE_MAP.get(mo["reward_type"], f"Unknown (type {mo['reward_type']})")
        mo_title = (flavor_texts.get("alert_titles") or {}).get("major_order", "MAJOR ORDER")
        lines.append(f"**{mo_title}**")
        lines.append(f"> {mo['briefing']}")
        if mo.get('description'):
            lines.append(f"> {mo['description']}")
        lines.append(f"> **Reward:** {mo['reward_amount']} {reward_label}")
        lines.append(f"> **Expires in:** {format_duration(_time_remaining_hours(mo['expiration']))}")
        lines.append("> **Objectives:**")
        top_planets_by_index = {p["index"]: p for p in parsed_data.get("planets", [])}
        mo_task_statuses = parsed_data.get("mo_task_statuses", {})
        for task in mo["tasks"]:
            planet_idx = None
            if task["decoded_type"] in ("liberate_planet", "defense_planet"):
                for vtype, val in zip(task["value_types"], task["values"]):
                    if vtype == 12:
                        planet_idx = val
                        break
            status_info = None
            if planet_idx is not None and planet_idx in mo_task_statuses:
                status_info = dict(mo_task_statuses[planet_idx])
                top_p = top_planets_by_index.get(planet_idx)
                if top_p:
                    status_info["liberation_time_hours"] = top_p.get("liberation_time_hours")
                    status_info["event"] = top_p.get("event")
            lines.append(f">   • {_render_task_label(task, planet_index_to_name)}{_format_mo_task_status(status_info, discord=True)}")
        lines.append("")

    selected_ids = set(flavor_texts.get("selected_dispatches") or [])
    selected_dispatches = [d for d in (parsed_data.get("dispatches") or []) if d["id"] in selected_ids]
    if selected_dispatches:
        lines.append("**RECENT INTEL**")
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

    theater_order, theaters = _build_theaters(parsed_data)
    limits = flavor_texts.get("limits", {})
    for faction in theater_order:
        if limits.get(faction):
            theaters[faction] = theaters[faction][:1]

    for i, faction in enumerate(theater_order):
        if i > 0:
            lines.append("---")
        display = _THEATER_DISPLAY.get(faction, faction.upper())
        lines.append(f"**{display} FRONT**")
        theater_text = theater_flavors.get(faction)
        if theater_text:
            lines.append(f"*{theater_text}*")
        lines.append("")

        for planet in theaters[faction]:
            is_def = planet["is_defense"]
            on_dss = planet["index"] == dss_planet_index

            if is_def:
                outcome = _defense_header(planet)
            else:
                lib_time = planet.get("liberation_time_hours")
                outcome = f"LIBERATED in {format_duration(lib_time)}" if lib_time is not None else "Establishing a Beachhead"
            lines.append(f"**{planet['name']}: {outcome}**")

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
                lines.append("> **DSS in Orbit**")
                for action in dss["tactical_actions"]:
                    if action["status_label"] == "active":
                        expire = action.get("status_expire")
                        duration_str = ""
                        if expire:
                            hrs = _time_remaining_hours(expire)
                            if hrs and hrs > 0:
                                duration_str = f" — Active for {format_duration(hrs)}"
                        lines.append(f"> **{action['name']}**{duration_str}")
                        desc = _strip_html(action["strategic_description"])
                        if desc:
                            lines.append(f"> │ *{desc}*")

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

            hazards = [h for h in planet.get("hazards", []) if h.get("name") and h["name"] != "None"]
            for hazard in hazards:
                lines.append(f"> {_format_hazard_discord(hazard, classifications)}")

            for cm in (flavor_texts.get("custom_modifiers") or []):
                if planet["name"] in cm.get("planets", []) and cm.get("text", "").strip():
                    pre, suf = _TIER_DISCORD.get(cm.get("tier", "none"), ("", ""))
                    lines.append(f"> {pre}{cm['text'].strip()}{suf}")

            active_regions = [r for r in planet.get("regions", []) if r.get("players", 0) > 0 and r["health"] < r["max_health"]]
            if active_regions:
                lines.append("")
                lines.append("__**Population Centers:**__")
                for r in active_regions:
                    pct = round((1 - r["health"] / r["max_health"]) * 100, 1) if r["max_health"] else 0.0
                    size = f"{r['size']} — " if r.get("size") else ""
                    status = _format_region_status(r)
                    status_str = f"**{status}**" if ("Secured in" in status or "Lost in" in status) else status
                    lines.append(f"> **{r['name'].upper()}** ({size}{r['players']} Helldivers) — {pct}% cleared | {status_str}")

            lines.append("")

    if dss:
        lines.append("")
        lines.extend(_format_dss_discord(dss))

    return "\n".join(lines)


def format_video(parsed_data, classifications, flavor_texts=None):
    """Formats parsed war data as plain text for video scripts.

    Args:
        parsed_data: dict from parse_all()
        classifications: dict from classify_items()
        flavor_texts: optional dict with "theaters" and "planets" sub-dicts
    Returns:
        str of plain text with no markdown
    """
    flavor_texts = flavor_texts or {}
    theater_flavors = flavor_texts.get("theaters", {})
    planet_flavors = flavor_texts.get("planets", {})

    MAJOR_SEP = "================================================"
    MINOR_SEP = "------------------------------------------------"

    lines = []
    mo = parsed_data.get("major_order")
    dss = parsed_data.get("dss")
    dss_planet_index = dss["planet_index"] if dss else None

    lines.append(MAJOR_SEP)
    lines.append("GALACTIC WAR UPDATE")
    lines.append(MAJOR_SEP)
    lines.append("")

    if mo:
        planet_index_to_name = _load_planet_index_to_name()
        reward_label = _REWARD_TYPE_MAP.get(mo["reward_type"], f"Unknown (type {mo['reward_type']})")
        mo_title = (flavor_texts.get("alert_titles") or {}).get("major_order", "MAJOR ORDER")
        lines.append(mo_title)
        lines.append(MINOR_SEP)
        lines.append(f"    {mo['briefing']}")
        if mo.get('description'):
            lines.append(f"    {mo['description']}")
        lines.append(f"    Reward: {mo['reward_amount']} {reward_label}")
        lines.append(f"    Expires in: {format_duration(_time_remaining_hours(mo['expiration']))}")
        lines.append("    Objectives:")
        top_planets_by_index = {p["index"]: p for p in parsed_data.get("planets", [])}
        mo_task_statuses = parsed_data.get("mo_task_statuses", {})
        for task in mo["tasks"]:
            planet_idx = None
            if task["decoded_type"] in ("liberate_planet", "defense_planet"):
                for vtype, val in zip(task["value_types"], task["values"]):
                    if vtype == 12:
                        planet_idx = val
                        break
            status_info = None
            if planet_idx is not None and planet_idx in mo_task_statuses:
                status_info = dict(mo_task_statuses[planet_idx])
                top_p = top_planets_by_index.get(planet_idx)
                if top_p:
                    status_info["liberation_time_hours"] = top_p.get("liberation_time_hours")
                    status_info["event"] = top_p.get("event")
            lines.append(f"      - {_render_task_label(task, planet_index_to_name)}{_format_mo_task_status(status_info, discord=False)}")
        lines.append("")

    selected_ids = set(flavor_texts.get("selected_dispatches") or [])
    selected_dispatches = [d for d in (parsed_data.get("dispatches") or []) if d["id"] in selected_ids]
    if selected_dispatches:
        lines.append(MAJOR_SEP)
        lines.append("RECENT INTEL")
        lines.append(MAJOR_SEP)
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

    theater_order, theaters = _build_theaters(parsed_data)
    limits = flavor_texts.get("limits", {})
    for faction in theater_order:
        if limits.get(faction):
            theaters[faction] = theaters[faction][:1]

    for faction in theater_order:
        lines.append(MAJOR_SEP)
        lines.append(f"{faction.upper()} FRONT")
        lines.append(MAJOR_SEP)
        theater_text = theater_flavors.get(faction)
        if theater_text:
            lines.append(theater_text)
        lines.append("")

        for planet in theaters[faction]:
            is_def = planet["is_defense"]
            on_dss = planet["index"] == dss_planet_index
            dss_tag = " (DSS IN ORBIT)" if on_dss else ""

            lines.append(MINOR_SEP)
            lines.append(f"{planet['name'].upper()}{dss_tag}")
            lines.append(MINOR_SEP)

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

            lines.append(f"    Sector: {planet['sector']} | Biome: {planet['biome']}")
            campaign_type_label = _CAMPAIGN_TYPE_MAP.get(planet['campaign_type'], f"Unknown ({planet['campaign_type']})")
            lines.append(f"    Campaign Level: {planet['campaign_level']} | Type: {campaign_type_label}")
            lines.append(f"    Players: {planet['player_count']:,}")
            lines.append(f"    {progress_label}: {planet['progress_pct']}%")
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

            active_regions = [r for r in planet.get("regions", []) if r.get("players", 0) > 0 and r["health"] < r["max_health"]]
            if active_regions:
                lines.append("    Population Centers:")
                for r in active_regions:
                    pct = round((1 - r["health"] / r["max_health"]) * 100, 1) if r["max_health"] else 0.0
                    size = f"{r['size']} — " if r.get("size") else ""
                    status = _format_region_status(r)
                    lines.append(f"      {r['name']} ({size}{r['players']} Helldivers) — {pct}% cleared | {status}")

            planet_text = planet_flavors.get(planet["name"])
            if planet_text:
                lines.append(f"    {planet_text}")
            lines.append("")

    if dss:
        lines.append(MAJOR_SEP)
        lines.extend(_format_dss_video(dss))

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


def get_theater_data(parsed_data, limits=None, classifications=None, planet_modifiers=None):
    """Returns structured theater data for the flavor editor reference panels.

    Pre-formats all durations and task labels so the JS template has no calculation to do.
    Returns a list of theater dicts, one per faction, in display order.
    """
    limits = limits or {}
    classifications = classifications or {}
    planet_modifiers = planet_modifiers or {}
    theater_order, theaters = _build_theaters(parsed_data)
    for faction in theater_order:
        if limits.get(faction):
            theaters[faction] = theaters[faction][:1]
    mo = parsed_data.get("major_order")
    dss = parsed_data.get("dss")
    mo_indices = _get_mo_planet_indices(parsed_data)

    mo_task_labels = []
    if mo:
        planet_index_to_name = _load_planet_index_to_name()
        mo_task_labels = [_render_task_label(t, planet_index_to_name) for t in mo.get("tasks", [])]

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
                pct = round((1 - r["health"] / r["max_health"]) * 100, 1) if r["max_health"] else 0.0
                regions.append({
                    "name": r["name"],
                    "size": r.get("size", ""),
                    "players": r["players"],
                    "progress_pct": pct,
                    "is_available": r["is_available"],
                    "status": _format_region_status(r),
                })
            planet_refs.append({
                "name": p["name"],
                "player_count": f"{p['player_count']:,}",
                "progress_pct": p["progress_pct"],
                "time_status": time_status,
                "is_defense": p["is_defense"],
                "is_mo": p["index"] in mo_indices,
                "biome": p.get("biome", ""),
                "biome_description": p.get("biome_description", ""),
                "hazards": hazards,
                "regions": regions,
                "modifier_options": modifier_options,
                "active_modifiers": planet_modifiers.get(p["name"], {}),
            })

        mo_ref = None
        if mo and mo_relevant:
            reward_label = _REWARD_TYPE_MAP.get(mo["reward_type"], "Unknown")
            mo_ref = {
                "briefing": mo["briefing"],
                "reward": f"{mo['reward_amount']} {reward_label}",
                "expires": format_duration(_time_remaining_hours(mo["expiration"])),
                "tasks": mo_task_labels,
            }

        dss_ref = None
        if dss_in_theater:
            ftl = format_duration(_time_remaining_hours(dss["election_end"])) if dss.get("election_end") else None
            dss_ref = {
                "planet_name": dss["planet_name"],
                "ftl_jump": ftl,
                "actions": [
                    {
                        "name": a["name"],
                        "status": a["status_label"],
                        "cost_label": _dss_cost_label(a),
                        "phrase": _dss_status_phrase(a),
                        "description": _strip_html(a["strategic_description"]),
                    }
                    for a in dss["tactical_actions"]
                ],
            }

        result.append({
            "faction": faction,
            "planets": planet_refs,
            "mo": mo_ref,
            "dss": dss_ref,
        })

    return result


def get_modifier_panel_data(parsed_data, flavor):
    """Returns data for the consolidated Gameplay Modifiers panel.

    Builds the Special Factions rows (faction modifier × applicable planets)
    and passes through custom_modifiers with the active planet list.
    """
    planet_modifiers = flavor.get("planet_modifiers", {})
    limits = flavor.get("limits", {})

    theater_order, theaters = _build_theaters(parsed_data)
    for faction in theater_order:
        if limits.get(faction):
            theaters[faction] = theaters[faction][:1]

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
