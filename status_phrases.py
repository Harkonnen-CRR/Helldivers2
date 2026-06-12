"""SEAF status phrases — resolve a progress percentage to an in-universe status phrase.

Three tracks (liberation / defense / region) share the same percentage bands; a percentage
resolves to the band with the highest `min` that is <= the value. The phrase content lives in
fixtures/status_phrases.json (user-editable), never hardcoded here.
"""
import json
import os

_PHRASES_PATH = os.path.join("fixtures", "status_phrases.json")
_TRACKS = None  # module-level cache; loaded once (the app restarts when the file is edited)

_NO_DATA_PHRASE = "Awaiting Field Reports"


def _load():
    global _TRACKS
    if _TRACKS is None:
        with open(_PHRASES_PATH) as f:
            data = json.load(f)
        # Sort each track's bands ascending by min so resolution can scan for the highest
        # min <= pct, regardless of how the file happens to be ordered.
        _TRACKS = {track: sorted(bands, key=lambda b: b["min"]) for track, bands in data.items()}
    return _TRACKS


def get_status_phrase(track, pct):
    """Resolve `pct` to the in-universe status phrase for `track`.

    - track: "liberation" | "defense" | "region" — unknown raises ValueError (fail loud).
    - pct None  -> "Awaiting Field Reports" (data still calculating).
    - pct is clamped to [0, 100].
    - Resolves to the band with the highest `min` that is <= pct.
    """
    tracks = _load()
    if track not in tracks:
        raise ValueError(f"Unknown status phrase track: {track!r} "
                         f"(expected one of {sorted(tracks)})")
    if pct is None:
        return _NO_DATA_PHRASE

    pct = max(0, min(100, pct))
    label = tracks[track][0]["label"]  # the min=0 band is always the floor
    for band in tracks[track]:
        if band["min"] <= pct:
            label = band["label"]
        else:
            break
    return label
