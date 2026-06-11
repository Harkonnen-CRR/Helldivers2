"""Layer B (supplemental lore) — fetch + parse a planet's wiki ARTICLE into distinct,
standalone lore entries.

This is the SUPPLEMENTAL reference layer: it never overwrites the live API data, never
reaches the final output unless the user explicitly inserts an entry, and is shaped so the
Discord bot can read it later. The live API (api_client.py) remains the authoritative source
for biome/description/sector/regions; this module only adds the rich prose lore/history that
the API does NOT carry (it lives in the wiki article pages, not the data module).

Source: helldivers.wiki.gg MediaWiki TextExtracts API — `prop=extracts` with
`explaintext=1&exsectionformat=wiki` returns clean plain text with `== Header ==` markers, so
we can split it into entries with no HTML parsing and no extra dependencies.

This first pass is data-layer only: fetch + parse + return the entry list. No caching, no UI.
Run `python wiki_lore.py [PageName]` to inspect the extracted entries for one planet.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests

WIKI_API = "https://helldivers.wiki.gg/api.php"
MODULE_RAW = "https://helldivers.wiki.gg/index.php?title=Module:Data/PlanetStatistics&action=raw"
USER_AGENT = "SEAF-Daily-Briefing/1.0 (Helldivers 2 war-update tool; contact via app)"

DATA_DIR = "data"
PAGENAME_MAP_PATH = os.path.join(DATA_DIR, "planet_pagenames.json")
LORE_CACHE_PATH = os.path.join(DATA_DIR, "planet_lore.json")

# index -> pagename, pulled from the wiki Lua module. Field order there is stable
# (`["index"] = N, ["Name"] = "...", ["pagename"] = "..."`), so a targeted regex avoids a
# Lua parser / slpp dependency — we only want these two fields.
_PAGENAME_RE = re.compile(r'\["index"\] = (\d+), \["Name"\] = "[^"]*", \["pagename"\] = "([^"]*)"')

# Sections we never want as lore entries (images, citations, redundant stats block).
_SKIP_SECTIONS = {"gallery", "media", "references", "notes references", "statistics", "see also"}

# Generic/structural section names that are NOT useful as highlight terms (item 5b) — the
# term index should hold proper-noun lore (planet name, named operations/events/monuments),
# not section labels.
_GENERIC_TITLES = {"summary", "lore", "regions", "trivia", "notes",
                   "battles for planet", "timeline", "terrain"}

# H2 section name -> entry category. Subsections of "Lore" are tagged history (see below).
_CATEGORY_MAP = {
    "lore": "lore",
    "regions": "poi",
    "battles for planet": "battles",
    "trivia": "trivia",
    "notes": "notes",
}

# Matches a wiki section header line: == Title == / === Title === (levels 2-6).
_HEADER_RE = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.MULTILINE)


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _clean(text):
    """Tidy the extract: collapse the double-spaces left where links were stripped and the
    runs of blank lines the extract leaves around headers."""
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" *\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_planet_lore(pagename):
    """Fetch + parse one planet's wiki article. Returns a dict:
    {pagename, page_revid, entries: [{id, category, parent, title, text}], terms: [...]}
    or None if the page is missing."""
    params = {
        "action": "query",
        "format": "json",
        "prop": "extracts|revisions",
        "explaintext": 1,
        "exsectionformat": "wiki",
        "rvprop": "ids|timestamp",
        "titles": pagename,
    }
    resp = requests.get(WIKI_API, params=params, headers={"User-Agent": USER_AGENT}, timeout=25)
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})
    page = next(iter(pages.values()), {})
    if "missing" in page or "extract" not in page:
        return None

    extract = page["extract"]
    revid = (page.get("revisions") or [{}])[0].get("revid")

    # Split the extract into (level, title, body) segments by header position.
    matches = list(_HEADER_RE.finditer(extract))
    segments = []
    intro = extract[: matches[0].start()] if matches else extract
    intro = _clean(intro)
    if intro:
        segments.append((1, "Summary", intro))  # level 1 = the lead/intro, no header
    for i, m in enumerate(matches):
        level = len(m.group(1))
        title = m.group(2).strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(extract)
        body = _clean(extract[m.end():end])
        segments.append((level, title, body))

    # Build standalone entries. Track the current H2 as the parent/group for H3+ entries.
    entries = []
    current_h2 = None
    skip_group = False
    for level, title, body in segments:
        if level == 1:  # intro
            entries.append({"id": "summary", "category": "summary",
                            "parent": None, "title": title, "text": body})
            continue
        if level == 2:
            current_h2 = title
            skip_group = title.lower() in _SKIP_SECTIONS
        if skip_group:
            continue
        if not body:  # a heading with only subsections under it -> no standalone entry
            continue
        group = current_h2 if level > 2 else title
        base = _CATEGORY_MAP.get(group.lower(), "lore")
        category = "history" if (level > 2 and group.lower() == "lore") else base
        parent = current_h2 if level > 2 else None
        entries.append({
            "id": _slug(f"{parent}-{title}" if parent else title),
            "category": category,
            "parent": parent,
            "title": title,
            "text": body,
        })

    # Term index seed: the planet name + named lore titles (drop generic section labels).
    terms = sorted({pagename, *(e["title"] for e in entries
                                if e["title"].lower() not in _GENERIC_TITLES)})

    return {"pagename": pagename, "page_revid": revid, "entries": entries, "terms": terms}


def fetch_pagename_map():
    """index -> wiki pagename, from the Lua data module (one request)."""
    resp = requests.get(MODULE_RAW, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return {int(idx): name for idx, name in _PAGENAME_RE.findall(resp.text)}


def _load_pagename_map(refresh=False):
    """Cached index -> pagename map; fetched + cached to disk on first use."""
    if not refresh and os.path.exists(PAGENAME_MAP_PATH):
        with open(PAGENAME_MAP_PATH) as f:
            return {int(k): v for k, v in json.load(f).items()}
    mapping = fetch_pagename_map()
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PAGENAME_MAP_PATH, "w") as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)
    return mapping


def _load_lore_cache():
    if os.path.exists(LORE_CACHE_PATH):
        with open(LORE_CACHE_PATH) as f:
            return json.load(f)
    return {}


def _save_lore_cache(cache):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LORE_CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def _fetch_into(index, cache, pagenames):
    """Fetch one planet's lore and store it in the cache dict (keyed by str index)."""
    pagename = pagenames.get(index)
    if not pagename:
        return None
    data = fetch_planet_lore(pagename)
    if data is None:
        return None
    data["index"] = index
    data["fetched"] = datetime.now(timezone.utc).isoformat()
    cache[str(index)] = data
    return data


def get_planet_lore(index, refresh=False):
    """Lazy single access point: return a planet's lore by index, fetching + caching to
    data/planet_lore.json on first access. The editor, the search feature, the diver's-eye
    view (2c), and the Discord bot all go through here. Returns None if no wiki page."""
    index = int(index)
    cache = _load_lore_cache()
    key = str(index)
    if not refresh and key in cache:
        return cache[key]
    pagenames = _load_pagename_map()
    if index not in pagenames:
        # Planet new since our last map pull (e.g. added in a game patch) — refresh once so
        # newly-added planets resolve without manual intervention.
        pagenames = _load_pagename_map(refresh=True)
    data = _fetch_into(index, cache, pagenames)
    if data is not None:
        _save_lore_cache(cache)
    return data


def warm_all(indices=None, delay=0.2):
    """Bulk-populate the lore cache (turns the lazy cache into a full corpus for
    offline/server/bot use). Skips already-cached planets; one disk write at the end.
    Returns (fetched, skipped, missing)."""
    cache = _load_lore_cache()
    pagenames = _load_pagename_map()
    targets = list(indices) if indices is not None else sorted(pagenames)
    fetched = skipped = missing = 0
    for idx in targets:
        if str(idx) in cache:
            skipped += 1
            continue
        if _fetch_into(int(idx), cache, pagenames) is not None:
            fetched += 1
            if delay:
                time.sleep(delay)  # be polite to the wiki
        else:
            missing += 1
    _save_lore_cache(cache)
    return fetched, skipped, missing


if __name__ == "__main__":
    arg = " ".join(sys.argv[1:]) or "Crimsica"
    # An integer arg exercises the lazy index path (get_planet_lore + cache); otherwise
    # treat the arg as a wiki pagename and fetch directly (no cache).
    if arg.isdigit():
        data = get_planet_lore(int(arg))
        src = f"index {arg} (lazy cache)"
    else:
        data = fetch_planet_lore(arg)
        src = f"page {arg!r}"
    if not data:
        print(f"No wiki lore found for {src}")
        sys.exit(1)
    print(f"=== {data['pagename']}  (revid {data['page_revid']}) — {len(data['entries'])} entries ===\n")
    for e in data["entries"]:
        head = f"[{e['category']}] {e['title']}"
        if e["parent"]:
            head += f"   (under: {e['parent']})"
        print(head)
        print(f"  id: {e['id']}")
        body = e["text"].replace("\n", "\n  ")
        print(f"  {body[:400]}{' …' if len(e['text']) > 400 else ''}\n")
    print("TERMS:", ", ".join(data["terms"]))
