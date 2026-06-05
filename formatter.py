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
            answer = input("Bold (gameplay effect)? y/n: ").strip().lower()
            if answer in ("y", "n"):
                classifications[key] = answer == "y"
                break
            print("Please enter y or n.")

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
    is_gameplay = classifications.get(key, False)
    name = hazard["name"]
    desc = hazard["description"]
    if is_gameplay:
        return f"**{name}** — *{desc}*"
    return f"{name} — *{desc}*"


def _format_hazard_video(hazard, classifications):
    key = f"hazard_{hazard['name']}"
    is_gameplay = classifications.get(key, False)
    desc = hazard["description"]
    if is_gameplay:
        return f"{hazard['name'].upper()} — {desc}"
    return f"{hazard['name'].title()} — {desc}"


def _format_dss_discord(dss, classifications):
    """Returns a list of Discord-formatted lines for the DSS section."""
    lines = []
    lines.append("**DEMOCRATIC SPACE STATION**")
    lines.append(f"> **Location:** {dss['planet_name']}")
    if dss.get("election_end"):
        remaining = _time_remaining_hours(dss["election_end"])
        lines.append(f"> **Next FTL Jump:** {format_duration(remaining)}")
    lines.append("> **Tactical Actions:**")
    for action in dss["tactical_actions"]:
        key = f"dss_{action['name']}"
        is_gameplay = classifications.get(key, False)
        desc = _strip_html(action["strategic_description"])
        desc_fmt = f"**{desc}**" if is_gameplay else f"*{desc}*"
        status = action["status_label"]
        expire_str = ""
        if status == "cooldown" and action.get("status_expire"):
            remaining = _time_remaining_hours(action["status_expire"])
            expire_str = f" | Time remaining: {format_duration(remaining)}"
        lines.append(f"> **{action['name']}** ({status.upper()}){expire_str}")
        lines.append(f">   {desc_fmt}")
        for fp in action.get("funding_progress", []):
            lines.append(
                f">   Funding: {fp['current']:.0f} / {fp['target']:.0f}"
                f" (+{fp['delta_per_second']:.4f}/sec)"
            )
    return lines


def _format_dss_video(dss, classifications):
    """Returns a list of plain-text lines for the DSS section."""
    lines = []
    lines.append("    DEMOCRATIC SPACE STATION")
    lines.append(f"    Location: {dss['planet_name']}")
    if dss.get("election_end"):
        remaining = _time_remaining_hours(dss["election_end"])
        lines.append(f"    Next FTL Jump: {format_duration(remaining)}")
    lines.append("    Tactical Actions:")
    for action in dss["tactical_actions"]:
        key = f"dss_{action['name']}"
        is_gameplay = classifications.get(key, False)
        desc = _strip_html(action["strategic_description"])
        status = action["status_label"]
        status_fmt = status.upper() if status in ("active", "cooldown") else status
        expire_str = ""
        if status == "cooldown" and action.get("status_expire"):
            remaining = _time_remaining_hours(action["status_expire"])
            expire_str = f" | Time remaining: {format_duration(remaining)}"
        name_fmt = action["name"].upper() if is_gameplay else action["name"]
        lines.append(f"      {name_fmt} — {status_fmt}{expire_str}")
        lines.append(f"        {desc}")
        for fp in action.get("funding_progress", []):
            lines.append(
                f"        Funding: {fp['current']:.0f} / {fp['target']:.0f}"
                f" (+{fp['delta_per_second']:.4f}/sec)"
            )
    return lines


def format_discord(parsed_data, classifications):
    """Formats parsed war data as Discord markdown.

    Args:
        parsed_data: dict from parse_all()
        classifications: dict from classify_items()
    Returns:
        str of Discord markdown with character count footer
    """
    lines = []
    mo = parsed_data.get("major_order")
    dss = parsed_data.get("dss")
    dss_planet_index = dss["planet_index"] if dss else None

    if mo:
        planet_index_to_name = _load_planet_index_to_name()
        reward_label = _REWARD_TYPE_MAP.get(mo["reward_type"], f"Unknown (type {mo['reward_type']})")
        lines.append("**MAJOR ORDER**")
        lines.append(f"> **{mo['title']}**")
        lines.append(f"> {mo['briefing']}")
        lines.append(f"> {mo['description']}")
        lines.append(f"> **Reward:** {mo['reward_amount']} {reward_label}")
        lines.append(f"> **Expires in:** {format_duration(_time_remaining_hours(mo['expiration']))}")
        lines.append("> **Tasks:**")
        for task in mo["tasks"]:
            lines.append(f">   • {_render_task_label(task, planet_index_to_name)}")
        lines.append("")

    theater_order, theaters = _build_theaters(parsed_data)

    for faction in theater_order:
        lines.append(f"**{faction.upper()} FRONT**")
        lines.append("*[THEATER FLAVOR TEXT]*")
        lines.append("")

        for planet in theaters[faction]:
            is_def = planet["is_defense"]
            on_dss = planet["index"] == dss_planet_index
            dss_tag = " *(DSS in orbit)*" if on_dss else ""
            lines.append(f"**{planet['name']}**{dss_tag}")

            progress_label = "Defense Progress" if is_def else "Liberation Progress"
            time_label = "Time to defense" if is_def else "Time to liberation"

            lines.append(f"> **Sector:** {planet['sector']} | **Biome:** {planet['biome']}")
            campaign_type_label = _CAMPAIGN_TYPE_MAP.get(planet['campaign_type'], f"Unknown ({planet['campaign_type']})")
            lines.append(f"> **Campaign Level:** {planet['campaign_level']} | **Type:** {campaign_type_label}")
            lines.append(f"> **Players:** {planet['player_count']:,}")
            lines.append(f"> **{progress_label}:** {planet['progress_pct']}%")
            lines.append(f"> **{time_label}:** {format_duration(planet['liberation_time_hours'])}")
            lines.append(f"> **Regen/sec:** {planet['regen_per_second']}")

            hazards = [h for h in planet.get("hazards", []) if h.get("name") and h["name"] != "None"]
            if hazards:
                lines.append("> **Hazards:**")
                for hazard in hazards:
                    lines.append(f"> {_format_hazard_discord(hazard, classifications)}")

            # EXOSTORM — remove this block if mechanic is retired
            if planet.get("exostorm"):
                ex = planet["exostorm"]
                lines.append(f"> **Exostorm** — *[MANUAL INPUT]* Class: {ex['class']}")

            lines.append("> *[PLANET FLAVOR TEXT]*")
            lines.append("")

    if dss:
        lines.append("")
        lines.extend(_format_dss_discord(dss, classifications))

    text = "\n".join(lines)
    used = len(text)
    remaining = 4000 - used
    text += f"\n*{used} characters used | {remaining} remaining for flavor text*"
    return text


def format_video(parsed_data, classifications):
    """Formats parsed war data as plain text for video scripts.

    Args:
        parsed_data: dict from parse_all()
        classifications: dict from classify_items()
    Returns:
        str of plain text with no markdown
    """
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
        lines.append("MAJOR ORDER")
        lines.append(MINOR_SEP)
        lines.append(f"    Title: {mo['title']}")
        lines.append(f"    Briefing: {mo['briefing']}")
        lines.append(f"    Reward: {mo['reward_amount']} {reward_label}")
        lines.append(f"    Expires in: {format_duration(_time_remaining_hours(mo['expiration']))}")
        lines.append("    Tasks:")
        for task in mo["tasks"]:
            lines.append(f"      - {_render_task_label(task, planet_index_to_name)}")
        lines.append("")

    theater_order, theaters = _build_theaters(parsed_data)

    for faction in theater_order:
        lines.append(MAJOR_SEP)
        lines.append(f"{faction.upper()} FRONT")
        lines.append(MAJOR_SEP)
        lines.append("[THEATER FLAVOR TEXT]")
        lines.append("")

        for planet in theaters[faction]:
            is_def = planet["is_defense"]
            on_dss = planet["index"] == dss_planet_index
            dss_tag = " (DSS IN ORBIT)" if on_dss else ""

            lines.append(MINOR_SEP)
            lines.append(f"{planet['name'].upper()}{dss_tag}")
            lines.append(MINOR_SEP)

            progress_label = "Defense Progress" if is_def else "Liberation Progress"
            time_label = "Time to defense" if is_def else "Time to liberation"

            lines.append(f"    Sector: {planet['sector']} | Biome: {planet['biome']}")
            campaign_type_label = _CAMPAIGN_TYPE_MAP.get(planet['campaign_type'], f"Unknown ({planet['campaign_type']})")
            lines.append(f"    Campaign Level: {planet['campaign_level']} | Type: {campaign_type_label}")
            lines.append(f"    Players: {planet['player_count']:,}")
            lines.append(f"    {progress_label}: {planet['progress_pct']}%")
            lines.append(f"    {time_label}: {format_duration(planet['liberation_time_hours'])}")
            lines.append(f"    Regen/sec: {planet['regen_per_second']}")

            hazards = [h for h in planet.get("hazards", []) if h.get("name") and h["name"] != "None"]
            if hazards:
                lines.append("    Hazards:")
                for hazard in hazards:
                    lines.append(f"      {_format_hazard_video(hazard, classifications)}")

            # EXOSTORM — remove this block if mechanic is retired
            if planet.get("exostorm"):
                ex = planet["exostorm"]
                lines.append(f"      EXOSTORM [MANUAL INPUT] — Class: {ex['class']}")

            lines.append("    [PLANET FLAVOR TEXT]")
            lines.append("")

    if dss:
        lines.append(MAJOR_SEP)
        lines.extend(_format_dss_video(dss, classifications))

    return "\n".join(lines)


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


def format_all(parsed_data, classifications):
    """Produces both Discord and video text outputs from parsed war data.

    Args:
        parsed_data: dict from parse_all()
        classifications: dict from classify_items()
    Returns:
        tuple of (discord_text, video_text)
    """
    return format_discord(parsed_data, classifications), format_video(parsed_data, classifications)


if __name__ == "__main__":
    from data_parser import parse_all
    parsed = parse_all()
    classifications = classify_items(parsed)
    discord_text = format_discord(parsed, classifications)
    video_text = format_video(parsed, classifications)
    save_outputs(discord_text, video_text)
    print(discord_text)
