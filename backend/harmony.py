"""Session-level 4-bar chord recipes + bass/pad/lead grid writers."""

from __future__ import annotations

import random
import re
from datetime import datetime, timezone
from typing import Any

from .midi_util import MINOR, STEPS_PER_BAR, degree_to_midi, parse_key

BARS = 4
LOOP_STEPS = BARS * STEPS_PER_BAR

# All v1 recipes are minor-roman; realize() always spells Aeolian of the tonic.
RECIPES: dict[str, dict[str, Any]] = {
    "i_VI_III_VII": {
        "id": "i_VI_III_VII",
        "label": "i–VI–III–VII",
        "romans": ["i", "VI", "III", "VII"],
        "lanes": ["melodic techno", "trance"],
        "pad_seventh": True,
    },
    "i_VII_VI_VII": {
        "id": "i_VII_VI_VII",
        "label": "i–VII–VI–VII",
        "romans": ["i", "VII", "VI", "VII"],
        "lanes": ["melodic techno"],
        "pad_seventh": False,
    },
    "pedal_i": {
        "id": "pedal_i",
        "label": "i–i–i–i",
        "romans": ["i", "i", "i", "i"],
        "lanes": ["peak", "techno"],
        "pad_seventh": False,
    },
    "i_iv_VI_V": {
        "id": "i_iv_VI_V",
        "label": "i–iv–VI–V",
        "romans": ["i", "iv", "VI", "V"],
        "lanes": ["prog house"],
        "pad_seventh": True,
    },
    "i_VI_iv_V": {
        "id": "i_VI_iv_V",
        "label": "i–VI–iv–V",
        "romans": ["i", "VI", "iv", "V"],
        "lanes": ["trance", "prog"],
        "pad_seventh": False,
    },
    "i_III_VI_VII": {
        "id": "i_III_VI_VII",
        "label": "i–III–VI–VII",
        "romans": ["i", "III", "VI", "VII"],
        "lanes": ["trance"],
        "pad_seventh": False,
    },
    "i_v_VI_VII": {
        "id": "i_v_VI_VII",
        "label": "i–v–VI–VII",
        "romans": ["i", "v", "VI", "VII"],
        "lanes": ["techno"],
        "pad_seventh": False,
    },
    "i_VI_i_VII": {
        "id": "i_VI_i_VII",
        "label": "i–VI–i–VII",
        "romans": ["i", "VI", "i", "VII"],
        "lanes": ["house"],
        "pad_seventh": False,
    },
    # Held / two-cell beds — fewer unique chords, less "game-OST" motion.
    "i_i_i_VII": {
        "id": "i_i_i_VII",
        "label": "i–i–i–VII",
        "romans": ["i", "i", "i", "VII"],
        "lanes": ["techno", "peak"],
        "pad_seventh": False,
    },
    "i_i_VII_VII": {
        "id": "i_i_VII_VII",
        "label": "i–i–VII–VII",
        "romans": ["i", "i", "VII", "VII"],
        "lanes": ["techno", "melodic techno"],
        "pad_seventh": False,
    },
    "i_VII_i_VII": {
        "id": "i_VII_i_VII",
        "label": "i–VII–i–VII",
        "romans": ["i", "VII", "i", "VII"],
        "lanes": ["techno"],
        "pad_seventh": False,
    },
    "i_i_VI_VI": {
        "id": "i_i_VI_VI",
        "label": "i–i–VI–VI",
        "romans": ["i", "i", "VI", "VI"],
        "lanes": ["melodic techno", "prog"],
        "pad_seventh": False,
    },
    "i_VI_i_VI": {
        "id": "i_VI_i_VI",
        "label": "i–VI–i–VI",
        "romans": ["i", "VI", "i", "VI"],
        "lanes": ["melodic techno", "house"],
        "pad_seventh": False,
    },
    "i_iv_i_iv": {
        "id": "i_iv_i_iv",
        "label": "i–iv–i–iv",
        "romans": ["i", "iv", "i", "iv"],
        "lanes": ["techno"],
        "pad_seventh": False,
    },
    "i_i_sus4_sus4": {
        "id": "i_i_sus4_sus4",
        "label": "i–i–sus4–sus4",
        "romans": ["i", "i", "sus4", "sus4"],
        "lanes": ["peak", "techno"],
        "pad_seventh": False,
    },
    "i_sus4_i_sus4": {
        "id": "i_sus4_i_sus4",
        "label": "i–sus4–i–sus4",
        "romans": ["i", "sus4", "i", "sus4"],
        "lanes": ["peak", "techno"],
        "pad_seventh": False,
    },
}

_ROMAN_DEGREE = {
    "i": 0,
    "ii": 1,
    "iii": 2,
    "iv": 3,
    "v": 4,
    "vi": 5,
    "vii": 6,
}
_QUALITY_INTERVALS = {
    "min": [0, 3, 7],
    "maj": [0, 4, 7],
    "dim": [0, 3, 6],
    "sus4": [0, 5, 7],
}
_SUS4_RE = re.compile(r"^(?:i[\s._-]*)?sus4$", re.I)
_NO_STYLE = frozenset(
    {"", "none", "no preference", "nopreference", "any", "all", "random", "n/a", "na"}
)
_BASS_TYPES = frozenset({"bass"})
_PAD_TYPES = frozenset({"pad", "pads", "strings", "chorus", "keys"})
_LEAD_TYPES = frozenset(
    {"lead", "synth", "arp", "pluck", "seq", "hoover", "guitar", "brass"}
)
_PHRASE_TYPES: tuple[str, ...] = (
    "runner",
    "hook_hold",
    "motif_echo",
    "call_answer",
    "sparse_pickup",
)
_PHRASE_WEIGHTS: dict[str, int] = {
    "runner": 8,
    "hook_hold": 2,
    "motif_echo": 1,
    "call_answer": 1,
    "sparse_pickup": 2,
}
# 16th gate patterns (gaps are the detail). Not 8ths on every downbeat.
_RUNNER_GATES: tuple[tuple[int, ...], ...] = (
    (0, 1, 2, 3, 4, 6, 8, 9, 10, 12, 14),
    (0, 2, 3, 4, 6, 8, 10, 11, 12, 14),
    (0, 1, 2, 4, 5, 6, 8, 10, 12, 13, 14),
    (0, 3, 4, 6, 7, 8, 11, 12, 14, 15),
    (1, 2, 3, 4, 6, 8, 10, 12, 14, 15),
    (0, 2, 3, 6, 8, 9, 11, 12, 14),
    (0, 1, 3, 4, 7, 8, 10, 12, 13, 15),
    (0, 2, 4, 5, 6, 8, 9, 12, 14),
    (0, 1, 2, 3, 6, 8, 9, 10, 11, 14),
    (2, 3, 4, 6, 7, 8, 11, 12, 14),
    (0, 3, 4, 8, 11, 12, 14, 15),
    (0, 1, 2, 4, 8, 9, 10, 12, 13, 14),
)
_RUNNER_GATES_SPARSE: tuple[tuple[int, ...], ...] = (
    (0, 3, 4, 8, 11, 12),
    (0, 6, 8, 14, 15),
    (0, 2, 3, 8, 10, 11),
    (4, 6, 8, 12, 14, 15),
    (0, 7, 8, 14),
)
_RUNNER_GATES_DENSE: tuple[tuple[int, ...], ...] = (
    (0, 1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 14, 15),
    (0, 1, 2, 3, 4, 6, 7, 8, 9, 10, 12, 13, 14),
    (0, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 15),
    (1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 14, 15),
)
_BOUNCER_GATES: tuple[tuple[int, ...], ...] = (
    (2, 6, 10, 14),
    (2, 6, 10, 12, 14),
    (0, 2, 6, 10, 14),
    (2, 6, 8, 10, 14),
    (6, 10, 14),
    (2, 3, 6, 10, 11, 14),
)
_BOUNCER_GATES_SPARSE: tuple[tuple[int, ...], ...] = (
    (2, 6, 10, 14),
    (6, 10, 14),
    (2, 10, 14),
)
_BOUNCER_GATES_DENSE: tuple[tuple[int, ...], ...] = (
    (2, 3, 6, 7, 10, 11, 14, 15),
    (0, 2, 6, 8, 10, 14),
    (2, 6, 8, 10, 12, 14),
    (2, 3, 6, 10, 11, 14, 15),
)
_GROOVE_GATES: tuple[tuple[int, ...], ...] = (
    (0, 3, 6, 8, 11, 14),
    (0, 6, 8, 14),
    (0, 4, 7, 8, 12, 15),
    (0, 3, 4, 8, 10, 11, 12),
    (0, 6, 8, 11, 12, 14),
    (0, 2, 3, 8, 10, 14, 15),
    (4, 6, 8, 12, 14, 15),
    (0, 7, 8, 14, 15),
)
_GROOVE_GATES_SPARSE: tuple[tuple[int, ...], ...] = (
    (0, 6, 8, 14),
    (0, 7, 8, 14),
    (4, 8, 14),
    (0, 8, 11, 14),
)
_GROOVE_GATES_DENSE: tuple[tuple[int, ...], ...] = (
    (0, 3, 4, 6, 8, 11, 12, 14),
    (0, 2, 3, 6, 8, 10, 11, 14, 15),
    (0, 3, 6, 7, 8, 11, 12, 14, 15),
    (0, 4, 6, 7, 8, 12, 14, 15),
)
_BASS_KINDS: tuple[str, ...] = ("runner", "bouncer", "groove")
# One-bar hit lists (step = 16th). Odd steps are true 16ths; even non-quarters are 8ths.
_MOTIF_RHYTHMS: tuple[tuple[int, ...], ...] = (
    (0, 4, 10),
    (0, 6, 8),
    (0, 3, 6, 12),
    (0, 8),
    (0, 4, 8, 14),
    (0, 5, 12),
    (0, 3, 4),
    (0, 4, 7, 8),
    (0, 8, 14, 15),
    (0, 12, 13, 14),
    (0, 3, 6, 8, 12),
)
_MOTIF_RHYTHMS_SPARSE: tuple[tuple[int, ...], ...] = (
    (0,),
    (0, 8),
    (0, 12),
    (0, 4, 10),
    (0, 14, 15),
    (0, 13, 14),
)
_MOTIF_RHYTHMS_DENSE: tuple[tuple[int, ...], ...] = (
    (0, 3, 4, 8, 11, 12),
    (0, 2, 3, 4, 8, 10, 11, 12),
    (0, 1, 2, 3, 8, 9, 10, 11),
    (0, 3, 4, 7, 8, 11, 12, 15),
    (0, 4, 8, 12, 13, 14, 15),
    (0, 6, 7, 8, 14, 15),
    (0, 2, 3, 4, 6, 7, 8, 12, 14, 15),
    (0, 3, 6, 8, 11, 12, 14, 15),
    (0, 4, 5, 8, 12, 13, 14),
    (0, 2, 4, 8, 10, 12),
)
_HOOK_SEQUENCE: tuple[int, ...] = (0, 4, 8, 12)
_PICKUP_SEQUENCE: tuple[int, ...] = (0, 8, 12, 13, 14, 15)
_TONIC_RE = re.compile(r"([A-G])(#|b)?", re.I)
THEME_ROMANS: tuple[str, ...] = ("i", "ii", "III", "iv", "v", "V", "VI", "VII")
THEME_ROMANS_PEAK: tuple[str, ...] = ("i", "VI", "VII", "sus4")
_PEAK_ROMANS = frozenset(THEME_ROMANS_PEAK)


def harmony_role(track_type: str | None) -> str | None:
    t = (track_type or "").split("__")[0].strip().lower()
    if t in _BASS_TYPES:
        return "bass"
    if t in _PAD_TYPES:
        return "pad"
    if t in _LEAD_TYPES:
        return "lead"
    return None


def tonic_minor_label(key: str) -> str:
    raw = (key or "C").strip()
    m = _TONIC_RE.match(raw)
    if not m:
        return "C minor"
    return f"{m.group(1).upper()}{m.group(2) or ''} minor"


def pc_to_degree_alter(pc: int, key: str) -> tuple[int, int]:
    """Map a pitch class to (Aeolian degree 0–6, semitone alter)."""
    tonic, _ = parse_key(key)
    rel = (int(pc) - tonic) % 12
    for deg, iv in enumerate(MINOR):
        if iv == rel:
            return deg, 0
    # Prefer a raised in-scale tone (V's E in F Aeolian → degree 6, +1).
    for deg, iv in enumerate(MINOR):
        if (iv + 1) % 12 == rel:
            return deg, 1
    for deg, iv in enumerate(MINOR):
        if (iv - 1) % 12 == rel:
            return deg, -1
    best_deg, best_alt, best_dist = 0, 0, 99
    for deg, iv in enumerate(MINOR):
        signed = rel - iv
        if signed > 6:
            signed -= 12
        elif signed < -6:
            signed += 12
        dist = abs(signed)
        if dist < best_dist:
            best_deg, best_alt, best_dist = deg, signed, dist
    return best_deg, best_alt


def _as_recipe(recipe: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(recipe, dict):
        rid = recipe.get("id") or recipe.get("recipe_id")
        if rid in RECIPES:
            out = dict(RECIPES[rid])
            if recipe.get("romans"):
                out["romans"] = list(recipe["romans"])
            if "pad_seventh" in recipe:
                out["pad_seventh"] = bool(recipe["pad_seventh"])
            return out
        if recipe.get("romans"):
            return {
                "id": rid or "custom",
                "label": recipe.get("label") or "–".join(recipe["romans"]),
                "romans": list(recipe["romans"]),
                "lanes": list(recipe.get("lanes") or []),
                "pad_seventh": bool(recipe.get("pad_seventh")),
            }
        raise KeyError(f"unknown recipe: {rid}")
    if recipe in RECIPES:
        return dict(RECIPES[recipe])
    raise KeyError(f"unknown recipe: {recipe}")


def is_peak_time_style(style: str) -> bool:
    blob = (style or "").strip().lower().replace("_", " ").replace("-", " ")
    if blob in _NO_STYLE:
        return False
    return "peak" in blob


def theme_romans_for_style(style: str = "") -> tuple[str, ...]:
    if is_peak_time_style(style):
        return THEME_ROMANS_PEAK
    return THEME_ROMANS


def _parse_roman(roman: str) -> tuple[int, str]:
    raw = (roman or "i").strip()
    if _SUS4_RE.match(raw.replace("(", "").replace(")", "")):
        return 0, "sus4"
    if "°" in raw:
        core = raw.replace("°", "")
        return _ROMAN_DEGREE[core.lower()], "dim"
    if raw.lower().endswith("o") and raw[:-1].lower() in _ROMAN_DEGREE:
        return _ROMAN_DEGREE[raw[:-1].lower()], "dim"
    deg = _ROMAN_DEGREE[raw.lower()]
    quality = "maj" if raw[:1].isupper() else "min"
    return deg, quality


def _realize_chord(roman: str, tonic: int, key_label: str, bar: int) -> dict[str, Any]:
    root_degree, quality = _parse_roman(roman)
    root_pc = (tonic + MINOR[root_degree]) % 12
    intervals = list(_QUALITY_INTERVALS[quality])
    pcs = [(root_pc + iv) % 12 for iv in intervals]
    alters: dict[str, int] = {}
    for pc in pcs:
        deg, alt = pc_to_degree_alter(pc, key_label)
        if alt:
            alters[str(deg)] = alt
    return {
        "bar": bar,
        "roman": roman,
        "root_degree": root_degree,
        "quality": quality,
        "root_pc": root_pc,
        "pcs": pcs,
        "intervals": intervals,
        "alters": alters,
    }


def realize(recipe: str | dict[str, Any], key: str) -> dict[str, Any]:
    """Spell `recipe` in natural minor of `key`'s tonic. Quality is ignored."""
    rec = _as_recipe(recipe)
    tonic, _ = parse_key(key)
    label = tonic_minor_label(key)
    romans = list(rec["romans"])[:BARS]
    while len(romans) < BARS:
        romans.append(romans[-1] if romans else "i")
    chords = [_realize_chord(r, tonic, label, i) for i, r in enumerate(romans)]
    for c in chords:
        c["enabled"] = True
    return {
        "version": 1,
        "bars": BARS,
        "key": label,
        "recipe_id": rec["id"],
        "label": rec["label"],
        "locked": False,
        "style_used": "",
        "chords": chords,
    }


def chord_enabled(chord: Any) -> bool:
    if not isinstance(chord, dict):
        return True
    if "enabled" not in chord:
        return True
    return bool(chord["enabled"])


def effective_chords(progression: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Enabled chords in order, tiled to 4 bars (wrap, don't sustain)."""
    raw = [c for c in list((progression or {}).get("chords") or [])[:BARS] if isinstance(c, dict)]
    cycle = [c for c in raw if chord_enabled(c)]
    if not cycle:
        cycle = raw[:1]
    if not cycle:
        return []
    return [cycle[i % len(cycle)] for i in range(BARS)]


def edit_chords(
    progression: dict[str, Any],
    key: str,
    *,
    bar: int,
    roman: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """Change one bar's roman and/or enabled flag. At least one bar stays on."""
    src = progression if isinstance(progression, dict) else {}
    chords = list(src.get("chords") or [])
    romans: list[str] = []
    flags: list[bool] = []
    for i in range(BARS):
        c = chords[i] if i < len(chords) and isinstance(chords[i], dict) else {}
        romans.append(str(c.get("roman") or "i"))
        flags.append(chord_enabled(c))
    b = int(bar)
    if b < 0 or b >= BARS:
        raise ValueError("bar must be 0..3")
    if roman is not None:
        raw = str(roman).strip()
        _parse_roman(raw)
        romans[b] = raw
    if enabled is not None:
        flags[b] = bool(enabled)
        if not any(flags):
            flags[b] = True
    matched = next(
        (rec for rec in RECIPES.values() if list(rec["romans"]) == romans),
        None,
    )
    recipe: str | dict[str, Any] = matched or {
        "id": "custom",
        "label": "–".join(romans),
        "romans": romans,
        "pad_seventh": False,
    }
    out = realize(recipe, key)
    out["locked"] = bool(src.get("locked"))
    out["style_used"] = src.get("style_used") or ""
    if src.get("diced_at"):
        out["diced_at"] = src["diced_at"]
    if not matched:
        out["recipe_id"] = "custom"
    out["label"] = "–".join(r if flags[i] else f"({r})" for i, r in enumerate(romans))
    for i, c in enumerate(out["chords"]):
        c["enabled"] = flags[i]
    return out


def apply_edited_harmony(
    *,
    key: str,
    progression: dict[str, Any],
    tracks: list[dict[str, Any]] | None = None,
    bar: int,
    roman: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    tracks = list(tracks or [])
    _validate_track_grids(tracks)
    prog = edit_chords(progression, key, bar=bar, roman=roman, enabled=enabled)
    midi_out = rewrite_bass_pad(prog, tracks)
    for track in tracks:
        if not isinstance(track, dict):
            continue
        tid = str(track.get("id") or "").strip()
        if not tid:
            continue
        prev = _track_midi(track)
        role = harmony_role(track.get("type") or tid)
        if role == "bass" and tid in midi_out and prev:
            midi_out[tid]["patternId"] = prev.get("patternId") or midi_out[tid]["patternId"]
        if role == "lead" and prev and prev.get("source") == "progression":
            ret = rewrite_lead_grid(prog, prev, octave=_track_octave(track, 4))
            ret["patternId"] = prev.get("patternId") or "prog-lead"
            ret["octave"] = _track_octave(track, 4)
            midi_out[tid] = ret
    return {"progression": prog, "midi": midi_out}


def recipe_unique_count(rid: str) -> int:
    rec = RECIPES.get(rid) or {}
    return len({str(r) for r in (rec.get("romans") or [])})


def is_two_cell_recipe(rid: str) -> bool:
    """Pedal, AABB, or ABAB. No 3–4 unique adventure cycles."""
    rec = RECIPES.get(rid) or {}
    romans = [str(r) for r in (rec.get("romans") or [])]
    if len(romans) != BARS:
        return False
    uniq = set(romans)
    if len(uniq) == 1:
        return True
    if len(uniq) != 2:
        return False
    a, b, c, d = romans
    return (a == c and b == d) or (a == b and c == d)


def _base_recipe_weight(rid: str) -> int:
    """Peak-techno default: sit on 1–2 chords. Adventure cycles stay rare."""
    rec = RECIPES.get(rid) or {}
    romans = [str(r) for r in (rec.get("romans") or [])]
    n = len(set(romans))
    if "III" in romans or n >= 4:
        return 1
    if n <= 1:
        return 6
    if n == 2:
        return 4
    return 2


def _style_recipe_weights(style: str) -> dict[str, int]:
    weights = {rid: _base_recipe_weight(rid) for rid in RECIPES}
    blob = (style or "").strip().lower()
    if blob in _NO_STYLE:
        return weights
    melodic = any(t in blob for t in ("melodic", "afterlife"))
    prog = any(t in blob for t in ("prog", "progressive", "anjunadeep"))
    trance = any(t in blob for t in ("trance", "uplifting", "anjunabeats", "3.0"))
    peak = is_peak_time_style(blob)
    techno = (
        any(t in blob for t in ("techno", "hard")) and not melodic and not peak
    )
    house = "house" in blob and not prog

    def bump(rid: str, factor: int) -> None:
        if rid in weights:
            weights[rid] = max(1, int(weights[rid]) * int(factor))

    if melodic:
        bump("i_i_VI_VI", 3)
        bump("i_VI_i_VI", 3)
        bump("i_i_VII_VII", 2)
        bump("i_VII_VI_VII", 2)
        bump("i_i_i_VII", 2)
    if prog:
        bump("i_i_VI_VI", 3)
        bump("i_VI_i_VI", 2)
        bump("i_iv_VI_V", 8)
    if trance:
        bump("i_VI_III_VII", 3)
        bump("i_VI_iv_V", 2)
        bump("i_III_VI_VII", 2)
        bump("i_i_VI_VI", 2)
    if peak:
        for rid in list(weights):
            romans = [str(r) for r in (RECIPES[rid].get("romans") or [])]
            if (
                not set(romans) <= _PEAK_ROMANS
                or not is_two_cell_recipe(rid)
                or recipe_unique_count(rid) != 2
            ):
                weights[rid] = 0
        bump("i_i_VI_VI", 3)
        bump("i_VI_i_VI", 3)
        bump("i_i_VII_VII", 3)
        bump("i_VII_i_VII", 3)
        bump("i_i_sus4_sus4", 3)
        bump("i_sus4_i_sus4", 3)
    if techno:
        for rid in list(weights):
            romans = [str(r) for r in (RECIPES[rid].get("romans") or [])]
            if recipe_unique_count(rid) >= 3 or "III" in romans:
                weights[rid] = 0
        bump("pedal_i", 3)
        bump("i_i_i_VII", 3)
        bump("i_i_VII_VII", 3)
        bump("i_VII_i_VII", 3)
        bump("i_iv_i_iv", 2)
    if house:
        bump("i_iv_VI_V", 2)
        bump("i_VI_i_VII", 2)
        bump("i_VI_i_VI", 2)
    return weights


def pick_recipe(
    style: str = "",
    avoid: str | None = None,
    *,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Weighted recipe pick. Never returns `avoid` if another recipe exists."""
    picker = rng or random.Random()
    ids = [rid for rid in RECIPES if is_two_cell_recipe(rid)] or list(RECIPES)
    weights = [_style_recipe_weights(style)[rid] for rid in ids]
    if avoid in RECIPES and any(rid != avoid for rid in ids):
        weights = [0 if rid == avoid else w for rid, w in zip(ids, weights)]
    if not any(weights):
        weights = [0 if rid == avoid else 1 for rid in ids]
    chosen = picker.choices(ids, weights=weights, k=1)[0]
    rec = RECIPES[chosen]
    return {
        "id": rec["id"],
        "label": rec["label"],
        "romans": list(rec["romans"]),
        "lanes": list(rec["lanes"]),
        "pad_seventh": bool(rec["pad_seventh"]),
    }


def _empty_grid(n: int = LOOP_STEPS) -> list[dict | None]:
    return [None] * n


def _root_quarters() -> list[dict | None]:
    grid: list[dict | None] = _empty_grid(STEPS_PER_BAR)
    for s in (0, 4, 8, 12):
        grid[s] = {"degree": 0, "length": 4, "vel": 100}
    return grid


def _rhythm_cell(cell: dict | None) -> dict | None:
    if not cell or not isinstance(cell, dict):
        return None
    return {
        "degree": 0,
        "length": max(1, int(cell.get("length", 1))),
        "vel": int(cell.get("vel", 100)),
    }


def _rhythm_bar(grid: list | dict | None) -> list[dict | None]:
    if isinstance(grid, dict):
        grid = grid.get("grid")
    if isinstance(grid, list) and len(grid) == LOOP_STEPS:
        return [_rhythm_cell(c) for c in grid[:STEPS_PER_BAR]]
    if isinstance(grid, list) and len(grid) == STEPS_PER_BAR:
        return [_rhythm_cell(c) for c in grid]
    return _root_quarters()


def _midi_state(
    *,
    pattern_id: str,
    octave: int,
    key: str,
    grid: list[dict | None],
) -> dict[str, Any]:
    return {
        "patternId": pattern_id,
        "octave": int(octave),
        "key": key,
        "bars": BARS,
        "source": "progression",
        "locked": False,
        "grid": grid,
    }


def _is_sus4_chord(chord: dict[str, Any] | None) -> bool:
    if not isinstance(chord, dict):
        return False
    if str(chord.get("quality") or "").lower() == "sus4":
        return True
    raw = str(chord.get("roman") or "").strip().lower().replace(" ", "")
    return raw in ("sus4", "isus4")


def _color_degree(chord: dict[str, Any], key: str) -> int:
    """Characteristic non-root tone: 4th on sus4, otherwise the triad's 3rd."""
    if _is_sus4_chord(chord):
        return 3
    pcs = chord.get("pcs") or []
    if len(pcs) >= 2:
        deg, _ = pc_to_degree_alter(int(pcs[1]), key)
        return int(deg)
    return (int(chord.get("root_degree") or 0) + 2) % 7


def _degree_for_hit(chord: dict[str, Any], key: str, step: int, *, first: bool) -> int:
    root = int(chord.get("root_degree") or 0)
    if _is_sus4_chord(chord) and not first:
        return _color_degree(chord, key)
    return root


def rewrite_bass_grid(
    progression: dict[str, Any],
    grid: list | dict | None = None,
    *,
    octave: int | None = None,
) -> dict[str, Any]:
    """64-step bass. Rhythm from `grid` (bar 0 if already 64).

    sus4 bars keep the root on the first hit and move later hits to the 4th
    so the quality is audible on a monophonic bass.
    """
    chords = effective_chords(progression) or progression["chords"]
    key = progression.get("key") or "C minor"
    octv = 2 if octave is None else int(octave)
    rhythm = _rhythm_bar(grid)
    out = _empty_grid()
    for bar, chord in enumerate(chords[:BARS]):
        first = True
        for s, src in enumerate(rhythm):
            if not src:
                continue
            deg = _degree_for_hit(chord, key, s, first=first)
            first = False
            out[bar * STEPS_PER_BAR + s] = {
                "degree": deg,
                "length": src["length"],
                "vel": src["vel"],
            }
    return _midi_state(pattern_id="prog-roots", octave=octv, key=key, grid=out)


def rewrite_lead_grid(
    progression: dict[str, Any],
    midi: dict[str, Any] | list | None = None,
    *,
    octave: int | None = None,
) -> dict[str, Any]:
    """Keep lead rhythm; retarget degrees to the bar's chord.

    sus4: first hit stays the root when there are more notes, otherwise the
    4th. Later downbeats and leftover minor-3rds become the 4th.
    """
    src = midi if isinstance(midi, dict) else {}
    raw = src.get("grid") if src else midi
    key = progression.get("key") or "C minor"
    octv = 4 if octave is None else int(octave)
    chords = effective_chords(progression) or list(progression.get("chords") or [])
    if isinstance(raw, list) and len(raw) == LOOP_STEPS:
        cells = list(raw)
    elif isinstance(raw, list) and len(raw) == STEPS_PER_BAR:
        cells = list(raw) * BARS
    else:
        rhythm = _rhythm_bar(raw)
        cells = []
        for _ in range(BARS):
            cells.extend(rhythm)
    out = _empty_grid()
    for bar in range(BARS):
        chord = chords[bar] if bar < len(chords) else None
        if not isinstance(chord, dict):
            continue
        root = int(chord.get("root_degree") or 0)
        color = _color_degree(chord, key)
        sus = _is_sus4_chord(chord)
        base = bar * STEPS_PER_BAR
        hit_idx = [s for s in range(STEPS_PER_BAR) if cells[base + s]]
        only = len(hit_idx) <= 1
        first = True
        for s in range(STEPS_PER_BAR):
            cell = cells[base + s]
            if not cell or not isinstance(cell, dict):
                continue
            deg = int(cell.get("degree", 0))
            if sus:
                if first and not only:
                    deg = root
                elif s % 4 == 0 or first or deg == 2:
                    deg = color
            first = False
            nxt: dict[str, Any] = {
                "degree": deg,
                "length": max(1, int(cell.get("length") or 1)),
                "vel": int(cell.get("vel") or 100),
            }
            if cell.get("oct") is not None:
                nxt["oct"] = cell["oct"]
            out[base + s] = nxt
    return _midi_state(
        pattern_id=str(src.get("patternId") or "prog-lead"),
        octave=octv,
        key=key,
        grid=out,
    )


def _full_gate_pool(kind: str) -> tuple[tuple[int, ...], ...]:
    """Unthinned sequences. Density keeps a fraction of the chosen one."""
    if kind == "bouncer":
        return _BOUNCER_GATES + _BOUNCER_GATES_DENSE
    if kind == "groove":
        return _GROOVE_GATES + _GROOVE_GATES_DENSE
    return _RUNNER_GATES + _RUNNER_GATES_DENSE


def _pick_bass_kind(rng: random.Random, density: float) -> str:
    # Dense → more 16th runners; mid → bounce + groove; sparse → bounce.
    weights = {
        "runner": 1.2 + density * 3.0,
        "bouncer": 3.2 - abs(density - 0.35) * 1.5,
        "groove": 2.8 + (1.0 - abs(density - 0.5)) * 1.5,
    }
    kinds = list(_BASS_KINDS)
    return rng.choices(kinds, weights=[max(0.2, weights[k]) for k in kinds], k=1)[0]


def _pick_runner_gates(
    rng: random.Random, density: float, kind: str = "runner"
) -> list[int]:
    sequence = list(rng.choice(_full_gate_pool(kind)))
    return _apply_density(sequence, density, rng)


def _runner_root_midi(chord: dict[str, Any], key: str, octave: int) -> int:
    return degree_to_midi(key, int(chord["root_degree"]), int(octave))


def _fit_pitch(midi_n: int, lo: int, hi: int, fallback: int) -> int:
    n = int(midi_n)
    while n > hi:
        n -= 12
    while n < lo:
        n += 12
    if lo <= n <= hi:
        return n
    return max(lo, min(hi, int(fallback)))


def _runner_detail_midi(
    root_midi: int,
    key: str,
    chord: dict[str, Any],
    *,
    step: int,
    lo: int,
    hi: int,
    octave: int,
    rng: random.Random,
    variance: float,
    avoid_pcs: set[int] | None,
    melodic: bool = False,
) -> int:
    """Mostly the root; variance adds 5th / neighbor / octave (lead moves more)."""
    fifth = degree_to_midi(key, (int(chord["root_degree"]) + 4) % 7, int(octave))
    second = degree_to_midi(key, (int(chord["root_degree"]) + 1) % 7, int(octave))
    seventh = degree_to_midi(key, (int(chord["root_degree"]) + 6) % 7, int(octave))
    third = degree_to_midi(key, _color_degree(chord, key), int(octave))
    oct_up = root_midi + 12 if root_midi + 12 <= hi else root_midi
    roll = rng.random()
    spice = (0.12 + 0.62 * variance) if melodic else (0.05 + 0.38 * variance)
    if roll < spice * 0.35:
        cand = oct_up if melodic else (oct_up if roll < spice * 0.2 else fifth)
    elif step % 4 != 0 and roll < spice * 0.7:
        cand = rng.choice((second, seventh, third) if melodic else (second, seventh))
    elif roll < spice:
        cand = rng.choice((fifth, third)) if melodic else (fifth if fifth <= hi else root_midi)
    else:
        cand = root_midi
    blocked = avoid_pcs or set()
    if blocked and cand % 12 in blocked:
        for alt in (fifth, second, seventh, third, oct_up, root_midi):
            if alt % 12 not in blocked and lo <= alt <= hi:
                cand = alt
                break
    return _fit_pitch(cand, lo, hi, root_midi)


def _runner_vel(step: int, rng: random.Random) -> int:
    if step % 4 == 0:
        return rng.choice((100, 110, 118))
    if step % 4 == 3:
        return rng.choice((88, 98, 108))
    return rng.choice((68, 76, 84))


def _runner_length(
    step: int, hits: list[int], i: int, length: float, kind: str = "runner"
) -> int:
    nxt = hits[i + 1] if i + 1 < len(hits) else STEPS_PER_BAR
    room = max(1, nxt - step)
    if kind == "bouncer":
        if length <= 0.25:
            return min(2, room)
        if length >= 0.7:
            return min(4, room)
        return min(2, room)
    if kind == "groove" and length <= 0.25:
        return 1
    if length <= 0.3:
        return 1
    if length >= 0.75 and step % 4 == 0:
        return min(room, 2 if length < 0.9 else 4)
    return 1 if room == 1 else (2 if length >= 0.65 and step % 4 == 0 else 1)


def write_runner_grid(
    progression: dict[str, Any],
    *,
    octave: int,
    density: float = 0.5,
    variance: float = 0.5,
    length: float = 0.5,
    seed: int | None = None,
    avoid: Any = None,
    pattern_id: str | None = None,
    kind: str = "runner",
) -> dict[str, Any]:
    """Gated techno bass: runner (16ths), bouncer (offbeats), or groove.

    Density picks the hit pattern (keep-rate of one sequence). Variance only
    changes pitches — same gates every bar.
    """
    key = progression.get("key") or "C minor"
    octv = int(octave)
    density = _clamp01(density)
    variance = _clamp01(variance)
    length = _clamp01(length)
    kind = kind if kind in _BASS_KINDS else "runner"
    rng = random.Random(seed)
    chords = effective_chords(progression) or list(progression["chords"][:BARS])
    lo = degree_to_midi(key, 0, octv)
    hi = lo + 14
    avoid_pcs = _avoid_pcs(avoid, key)
    hits = _pick_runner_gates(rng, density, kind)
    if not hits:
        hits = [0, 3, 4, 8, 11, 12]
    lengths = [_runner_length(s, hits, i, length, kind) for i, s in enumerate(hits)]
    melodic = str(pattern_id or "").startswith("prog-lead")
    scale = _scale_midis(key, lo, hi)
    out = _empty_grid()
    offsets: list[int] = []
    for bar, chord in enumerate(chords):
        root = _runner_root_midi(chord, key, octv)
        color_m = degree_to_midi(key, _color_degree(chord, key), octv)
        anchor = root
        chord_midis, _, _ = _chord_pools(chord, lo, hi)
        for i, s in enumerate(hits):
            if _is_sus4_chord(chord) and i > 0:
                anchor = color_m
            else:
                anchor = root
            replay = bar > 0 and offsets and (variance <= 0.0 or rng.random() >= variance)
            if replay:
                pitch = _fit_pitch(root + offsets[i], lo, hi, anchor)
            else:
                pitch = _runner_detail_midi(
                    anchor,
                    key,
                    chord,
                    step=s,
                    lo=lo,
                    hi=hi,
                    octave=octv,
                    rng=rng,
                    variance=variance,
                    avoid_pcs=avoid_pcs if bar == 0 and i == 0 else None,
                    melodic=melodic,
                )
            pool = chord_midis if s % 4 == 0 else scale
            if pool:
                pitch = min(pool, key=lambda m: (abs(m - pitch), m))
            if bar == 0:
                offsets.append(pitch - root)
            out[bar * STEPS_PER_BAR + s] = _cell_from_midi(
                pitch,
                key,
                lengths[i],
                _runner_vel(s, rng),
                octave=octv,
            )
    return _midi_state(
        pattern_id=pattern_id or f"prog-{kind}", octave=octv, key=key, grid=out
    )


def dice_bass_grid(
    progression: dict[str, Any],
    *,
    octave: int | None = None,
    density: float = 0.5,
    variance: float = 0.5,
    length: float = 0.5,
    seed: int | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    density = _clamp01(density)
    picked = kind if kind in _BASS_KINDS else _pick_bass_kind(random.Random(seed), density)
    return write_runner_grid(
        progression,
        octave=2 if octave is None else int(octave),
        density=density,
        variance=variance,
        length=length,
        seed=seed,
        kind=picked,
        pattern_id=f"prog-{picked}",
    )


def _close_midis(chord: dict[str, Any], octave: int, seventh: bool) -> list[int]:
    intervals = list(chord["intervals"])
    if seventh and 10 not in intervals and chord.get("quality") != "sus4":
        intervals = intervals + [10]
    root_pc = int(chord["root_pc"])
    base = (int(octave) + 1) * 12 + root_pc
    notes = []
    for iv in intervals:
        pc = (root_pc + iv) % 12
        m = base + ((pc - root_pc) % 12)
        notes.append(m)
    return notes


def _inversions(notes: list[int]) -> list[list[int]]:
    ordered = sorted(notes)
    out: list[list[int]] = []
    for i in range(len(ordered)):
        out.append(ordered[i:] + [n + 12 for n in ordered[:i]])
    return out


def _voicing_score(prev: list[int], cand: list[int]) -> tuple[int, int, int]:
    top = abs(cand[-1] - prev[-1])
    common = len(set(prev) & set(cand))
    total = 0
    for c in cand:
        total += min(abs(c - p) for p in prev)
    return (top, -common, total)


def _midi_to_voice(midi_n: int, key: str) -> dict[str, Any]:
    deg, alter = pc_to_degree_alter(int(midi_n) % 12, key)
    octv = None
    for o in range(-1, 11):
        if degree_to_midi(key, deg, o, alter=alter) == int(midi_n):
            octv = o
            break
    if octv is None:
        octv = int(midi_n) // 12 - 1
    voice: dict[str, Any] = {"degree": deg, "oct": octv}
    if alter:
        voice["alter"] = alter
    return voice


def voice_lead(
    chords: list[dict[str, Any]],
    start_octave: int,
    *,
    seventh: bool = False,
    key: str = "C minor",
) -> list[list[dict[str, Any]]]:
    """Close triad/tetrad per bar; inversion minimizes top-note motion."""
    voicings: list[list[dict[str, Any]]] = []
    prev_midis: list[int] | None = None
    for chord in chords:
        options = _inversions(_close_midis(chord, start_octave, seventh))
        if prev_midis is None:
            chosen = options[0]
        else:
            chosen = min(options, key=lambda cand: _voicing_score(prev_midis, cand))
        prev_midis = chosen
        voicings.append([_midi_to_voice(m, key) for m in chosen])
    return voicings


def rewrite_pad_grid(
    progression: dict[str, Any],
    *,
    octave: int = 3,
) -> dict[str, Any]:
    """64-step pad: one voicing per bar at step 0 of the bar, length 16."""
    key = progression.get("key") or "C minor"
    rec = RECIPES.get(progression.get("recipe_id") or "", {})
    seventh = bool(rec.get("pad_seventh"))
    voicings = voice_lead(
        effective_chords(progression) or progression["chords"],
        int(octave),
        seventh=seventh,
        key=key,
    )
    out = _empty_grid()
    for bar, voices in enumerate(voicings[:BARS]):
        if not voices:
            continue
        cell: dict[str, Any] = {
            "degree": voices[0]["degree"],
            "length": STEPS_PER_BAR,
            "vel": 90,
            "voices": voices,
        }
        if voices[0].get("alter"):
            cell["alter"] = voices[0]["alter"]
        out[bar * STEPS_PER_BAR] = cell
    return _midi_state(pattern_id="prog-voicing", octave=int(octave), key=key, grid=out)


def _split_midi(midi_n: int, key: str) -> tuple[int, int, int]:
    deg, alter = pc_to_degree_alter(int(midi_n) % 12, key)
    for octv in range(-1, 11):
        if degree_to_midi(key, deg, octv, alter=alter) == int(midi_n):
            return deg, octv, alter
    return deg, int(midi_n) // 12 - 1, alter


def _cell_from_midi(
    midi_n: int,
    key: str,
    length: int,
    vel: int = 100,
    *,
    octave: int | None = None,
) -> dict[str, Any]:
    deg, octv, alter = _split_midi(midi_n, key)
    cell: dict[str, Any] = {
        "degree": deg,
        "length": max(1, int(length)),
        "vel": vel,
    }
    if octave is None or int(octv) != int(octave):
        cell["oct"] = octv
    if alter:
        cell["alter"] = alter
    return cell


def _scale_midis(key: str, lo: int, hi: int) -> list[int]:
    return [m for m in range(lo, hi + 1) if pc_to_degree_alter(m % 12, key)[1] == 0]


def _pcs_in_range(pcs: list[int], lo: int, hi: int) -> list[int]:
    want = {int(p) % 12 for p in pcs}
    return [m for m in range(lo, hi + 1) if (m % 12) in want]


def _neighbors(pitch: int, scale: list[int]) -> list[int]:
    if not scale:
        return []
    if pitch in scale:
        i = scale.index(pitch)
    else:
        i = min(range(len(scale)), key=lambda j: abs(scale[j] - pitch))
    out: list[int] = []
    if i > 0:
        out.append(scale[i - 1])
    if i + 1 < len(scale):
        out.append(scale[i + 1])
    return out


def _pick_near(
    options: list[int],
    prev: int | None,
    *,
    avoid_pcs: set[int] | None = None,
    max_leap: int | None = 7,
    rng: random.Random,
) -> int | None:
    if not options:
        return None
    cand = list(options)
    if avoid_pcs:
        filtered = [m for m in cand if (m % 12) not in avoid_pcs]
        if filtered:
            cand = filtered
    if prev is not None and max_leap is not None:
        near = [m for m in cand if abs(m - prev) <= max_leap and m != prev]
        if not near:
            near = [m for m in cand if abs(m - prev) <= max_leap]
        if near:
            return rng.choice(near)
        return min(cand, key=lambda m: (abs(m - prev), m))
    if prev is not None:
        moved = [m for m in cand if m != prev]
        if moved:
            cand = moved
    return rng.choice(cand)


def _clamp01(value: Any, default: float = 0.5) -> float:
    if value is None:
        return default
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    if x != x:  # NaN
        return default
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _near_mid(value: float) -> bool:
    return 0.45 <= value <= 0.55


def _bar_start_pool(
    root_midis: list[int],
    third_fifth: list[int],
    chord_midis: list[int],
    prev: int | None,
    max_leap: int | None,
    avoid_pcs: set[int] | None,
    *,
    variance: float = 0.5,
    rng: random.Random | None = None,
) -> list[int]:
    """Root on s==0 only if it stays in the leap window and is not avoided."""
    roots = list(root_midis)
    others = list(third_fifth) if third_fifth else [m for m in chord_midis if m not in roots]
    if avoid_pcs and roots and all((m % 12) in avoid_pcs for m in roots):
        return others or chord_midis
    prefer_color = False
    if rng is not None and variance > 0.5:
        prefer_color = rng.random() < (variance - 0.5) * 2.0
    if prefer_color:
        cand = others or chord_midis or roots
        if prev is None or max_leap is None:
            return cand
        in_window = [m for m in cand if abs(m - prev) <= max_leap]
        return in_window or cand
    if prev is None or max_leap is None:
        return roots or others or chord_midis
    in_window = [m for m in roots if abs(m - prev) <= max_leap]
    if in_window:
        return in_window
    return others or chord_midis or roots


def _downbeat_pcs(grid: list | None, key: str) -> set[int]:
    if not isinstance(grid, list):
        return set()
    pcs: set[int] = set()
    for bar in range(BARS):
        step = bar * STEPS_PER_BAR
        if step >= len(grid) or not isinstance(grid[step], dict):
            continue
        cell = grid[step]
        midi_n = degree_to_midi(
            key,
            int(cell.get("degree", 0)),
            int(cell.get("oct", 4)),
            alter=int(cell.get("alter", 0) or 0),
        )
        pcs.add(midi_n % 12)
    return pcs


def _avoid_pcs(avoid: Any, key: str) -> set[int]:
    if not avoid:
        return set()
    if isinstance(avoid, dict):
        return _downbeat_pcs(avoid.get("grid"), avoid.get("key") or key)
    if isinstance(avoid, list) and avoid and isinstance(avoid[0], int):
        return {int(p) % 12 for p in avoid}
    if isinstance(avoid, list):
        return _downbeat_pcs(avoid, key)
    return set()


def _chord_pools(
    chord: dict[str, Any], lo: int, hi: int
) -> tuple[list[int], list[int], list[int]]:
    chord_midis = _pcs_in_range(chord["pcs"], lo, hi)
    root_midis = _pcs_in_range([chord["root_pc"]], lo, hi)
    third_fifth: list[int] = []
    if len(chord["pcs"]) >= 2:
        third_fifth.extend(_pcs_in_range([chord["pcs"][1]], lo, hi))
    if len(chord["pcs"]) >= 3:
        third_fifth.extend(_pcs_in_range([chord["pcs"][2]], lo, hi))
    if not third_fifth:
        third_fifth = list(chord_midis)
    return chord_midis, root_midis, third_fifth


def _hit_lengths(
    hits: list[int],
    rng: random.Random,
    *,
    long_ok: bool,
    length: float = 0.5,
) -> list[int]:
    lengths: list[int] = []
    defaultish = _near_mid(length)
    for i, s in enumerate(hits):
        nxt = hits[i + 1] if i + 1 < len(hits) else STEPS_PER_BAR
        room = max(1, nxt - s)
        if defaultish:
            if s % 4 == 0 and long_ok:
                choices = [n for n in (4, 8, 16) if n <= room]
                if not choices:
                    choices = [room]
                lengths.append(rng.choice(choices))
            elif s % 4 == 0:
                hi_len = min(4, room)
                lo_len = min(2, hi_len)
                lengths.append(rng.randint(lo_len, hi_len))
            elif s % 2 == 0:
                lengths.append(rng.randint(1, min(2, room)))
            else:
                lengths.append(1)
            continue
        if length >= 0.7 and s % 4 == 0:
            choices = [n for n in (4, 8, 16) if n <= room] or [room]
            lengths.append(max(choices) if length >= 0.9 else rng.choice(choices))
        elif length <= 0.25:
            cap = 1 if length < 0.1 else 2
            lengths.append(min(cap, room))
        elif s % 4 == 0 and long_ok:
            pool = (4, 8, 16) if length > 0.6 else (2, 4, 8)
            choices = [n for n in pool if n <= room] or [room]
            lengths.append(rng.choice(choices))
        elif s % 4 == 0:
            hi_len = min(4 if length > 0.35 else 2, room)
            if length > 0.55:
                lengths.append(max(1, hi_len))
            else:
                lengths.append(rng.randint(1, max(1, hi_len)))
        elif s % 2 == 0:
            if length < 0.4:
                lengths.append(1)
            else:
                lengths.append(rng.randint(1, min(2, room)))
        else:
            lengths.append(1)
    return lengths


def _phrase_weights(density: float) -> list[float]:
    weights = {p: float(_PHRASE_WEIGHTS[p]) for p in _PHRASE_TYPES}
    d = (density - 0.5) * 2.0
    if d < 0:
        weights["runner"] *= max(0.2, 1.0 + d * 0.85)
        weights["hook_hold"] *= 1.0 - d * 2.2
        weights["sparse_pickup"] *= 1.0 - d * 1.4
        weights["motif_echo"] *= max(0.2, 1.0 + d * 0.5)
        weights["call_answer"] *= max(0.2, 1.0 + d * 0.5)
    elif d > 0:
        weights["runner"] *= 1.0 + d * 1.4
        weights["hook_hold"] *= max(0.05, 1.0 - d * 1.3)
        weights["sparse_pickup"] *= max(0.08, 1.0 - d * 0.8)
        weights["motif_echo"] *= 1.0 + d * 0.4
        weights["call_answer"] *= 1.0 + d * 0.25
    return [max(0.01, weights[p]) for p in _PHRASE_TYPES]


def _pick_phrase(
    rng: random.Random,
    density: float = 0.5,
    variance: float = 0.5,
) -> str:
    ids = list(_PHRASE_TYPES)
    if _near_mid(density):
        weights = [_PHRASE_WEIGHTS[p] for p in ids]
    else:
        weights = _phrase_weights(density)
    return rng.choices(ids, weights=weights, k=1)[0]


def _sixteenth_count(hits: tuple[int, ...] | list[int]) -> int:
    return sum(1 for s in hits if int(s) % 2 == 1)


def _pick_motif(rng: random.Random, density: float) -> list[int]:
    """Full sequence. Caller applies density as the keep-rate."""
    pool = _MOTIF_RHYTHMS + _MOTIF_RHYTHMS_DENSE + _MOTIF_RHYTHMS_SPARSE
    weights = []
    for motif in pool:
        n16 = _sixteenth_count(motif)
        n = max(1, len(motif))
        hit_fit = 1.0 - abs((n / 12.0) - max(density, 0.25))
        six_fit = (n16 / n) * (0.2 + 1.2 * density)
        weights.append(max(0.08, 0.3 + hit_fit + six_fit))
    hits = list(rng.choices(pool, weights=weights, k=1)[0])
    if 0 not in hits:
        hits = [0, *hits]
    return hits


def _apply_density(
    sequence: list[int] | tuple[int, ...],
    density: float,
    rng: random.Random,
) -> list[int]:
    """Keep about `density` of the sequence, spread across the bar."""
    hits = sorted({int(s) for s in sequence if 0 <= int(s) < STEPS_PER_BAR})
    if not hits:
        return [0]
    d = _clamp01(density)
    if d >= 0.999:
        return hits
    exact = len(hits) * d
    target = int(exact)
    if rng.random() < (exact - target):
        target += 1
    target = 1 if d <= 0.0 else max(1, min(len(hits), target))
    if target >= len(hits):
        return hits
    preferred = 0 if 0 in hits else hits[0]
    rest = [s for s in hits if s != preferred]
    # Short sequences (hook/pickup): spread so holds have room.
    # Longer runners: random subset so 16ths stay in proportion.
    if len(hits) <= 4:
        kept = [preferred]
        while len(kept) < target and rest:
            def gap(step: int) -> int:
                return min(abs(step - k) for k in kept)

            best = max(gap(s) for s in rest)
            cands = [s for s in rest if gap(s) == best]
            pick = rng.choice(cands)
            kept.append(pick)
            rest.remove(pick)
        return sorted(kept)
    rng.shuffle(rest)
    return sorted([preferred, *rest[: target - 1]])


def _pick_lead_pitch(
    s: int,
    *,
    chord_midis: list[int],
    root_midis: list[int],
    third_fifth: list[int],
    scale: list[int],
    prev: int | None,
    avoid_pcs: set[int],
    max_leap: int | None,
    rng: random.Random,
    bar_start: bool,
    density: float = 0.5,
    variance: float = 0.5,
) -> int | None:
    # Hits are already chosen; density must not drop notes here.
    _ = density
    if s % 4 == 0:
        if bar_start or s == 0:
            pool = _bar_start_pool(
                root_midis,
                third_fifth,
                chord_midis,
                prev,
                max_leap,
                avoid_pcs,
                variance=variance,
                rng=rng,
            )
        else:
            # High variance: more 3rd/5th vs repeating the same chord tone.
            if variance >= 0.65 and third_fifth and rng.random() < variance:
                pool = third_fifth
            else:
                pool = third_fifth or chord_midis
        return _pick_near(pool, prev, avoid_pcs=avoid_pcs, max_leap=max_leap, rng=rng)
    if s % 2 == 0:
        pitch = None
        neighbor_p = 0.22 + 0.62 * variance
        if rng.random() < neighbor_p and prev is not None:
            pitch = _pick_near(
                _neighbors(prev, scale), prev, max_leap=max_leap, rng=rng
            )
        if pitch is None:
            color = third_fifth if variance >= 0.5 and third_fifth else chord_midis
            pitch = _pick_near(color, prev, max_leap=max_leap, rng=rng)
        return pitch
    if prev is not None:
        pitch = _pick_near(_neighbors(prev, scale), prev, max_leap=max_leap, rng=rng)
        if pitch is not None:
            return pitch
    pool = scale if variance >= 0.4 else (chord_midis or scale)
    return _pick_near(pool or chord_midis, prev, max_leap=max_leap, rng=rng)


def _snap_contour(
    target: int,
    s: int,
    *,
    chord_midis: list[int],
    scale: list[int],
    prev: int | None,
    lo: int,
    hi: int,
    max_leap: int | None,
) -> int | None:
    pool = chord_midis if s % 4 == 0 else (scale or chord_midis)
    pool = [m for m in pool if lo <= m <= hi]
    if prev is not None and max_leap is not None:
        near = [m for m in pool if abs(m - prev) <= max_leap]
        if near:
            pool = near
    if not pool:
        return None
    return min(pool, key=lambda m: (abs(m - target), m))


def _longest_rest(grid: list) -> int:
    best = 0
    run = 0
    covered = [False] * len(grid)
    for i, cell in enumerate(grid):
        if not cell:
            continue
        for j in range(i, min(len(grid), i + int(cell.get("length") or 1))):
            covered[j] = True
    for on in covered:
        if not on:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def _ensure_rest(grid: list, rng: random.Random) -> None:
    if _longest_rest(grid) >= 4:
        return
    longs = [
        i
        for i, c in enumerate(grid)
        if c and int(c.get("length") or 1) >= 8
    ]
    if longs:
        i = rng.choice(longs)
        grid[i]["length"] = max(4, int(grid[i]["length"]) - 4)
        return
    # Shorten a note rather than delete a hit (keeps motif echo aligned).
    cands = [i for i, c in enumerate(grid) if c and int(c.get("length") or 1) >= 2]
    if cands:
        i = rng.choice(cands)
        grid[i]["length"] = max(1, int(grid[i]["length"]) // 2)


def dice_lead_grid(
    progression: dict[str, Any],
    key: str,
    *,
    seed: int | None = None,
    octave: int | None = None,
    avoid: Any = None,
    density: float = 0.5,
    variance: float = 0.5,
    length: float = 0.5,
    phrase: str | None = None,
) -> dict[str, Any]:
    """4-bar phrase.

    density: which hits play (keep-rate of the phrase sequence).
    variance: how much pitches change across bars — not the rhythm.
    length: note duration.
    """
    minor_key = progression.get("key") or tonic_minor_label(key)
    octv = 4 if octave is None else int(octave)
    lo = degree_to_midi(minor_key, 0, octv)
    hi = lo + 14
    density = _clamp01(density)
    variance = _clamp01(variance)
    length = _clamp01(length)
    rng = random.Random(seed)
    scale = _scale_midis(minor_key, lo, hi)
    avoid_pcs = _avoid_pcs(avoid, minor_key)
    chords = effective_chords(progression) or list(progression["chords"][:BARS])
    phrase = phrase if phrase in _PHRASE_TYPES else _pick_phrase(rng, density)
    if phrase == "runner":
        return write_runner_grid(
            progression,
            octave=octv,
            density=density,
            variance=variance,
            length=length,
            seed=seed,
            avoid=avoid,
            pattern_id="prog-lead-runner",
        )
    out = _empty_grid()
    prev: int | None = None

    def pools(bar: int) -> tuple[list[int], list[int], list[int]]:
        return _chord_pools(chords[bar], lo, hi)

    def place(bar: int, s: int, length_steps: int, pitch: int) -> None:
        step = bar * STEPS_PER_BAR + s
        if step < 0 or step >= LOOP_STEPS:
            return
        out[step] = _cell_from_midi(pitch, minor_key, length_steps, 100, octave=octv)

    def first_pitch(bar: int, s: int) -> int | None:
        chord_midis, root_midis, third_fifth = pools(bar)
        allow_leap = prev is None
        cap = None if allow_leap else 7
        return _pick_lead_pitch(
            s,
            chord_midis=chord_midis,
            root_midis=root_midis,
            third_fifth=third_fifth,
            scale=scale,
            prev=prev,
            avoid_pcs=avoid_pcs if (bar == 0 and (s == 0 or prev is None)) else set(),
            max_leap=cap,
            rng=rng,
            bar_start=s == 0,
            density=density,
            variance=variance,
        )

    def stamp_hits(
        bar: int,
        hits: list[int],
        lengths: list[int],
        *,
        invert: bool = False,
        motif_pitches: list[int] | None = None,
    ) -> list[int]:
        nonlocal prev
        chord_midis, root_midis, third_fifth = pools(bar)
        written: list[int] = []
        anchor: int | None = None
        for i, s in enumerate(hits):
            note_len = lengths[i] if i < len(lengths) else 1
            cap = None if prev is None else 7
            pitch: int | None
            if motif_pitches is None:
                pitch = first_pitch(bar, s)
            else:
                if i == 0:
                    pitch = _pick_lead_pitch(
                        0,
                        chord_midis=chord_midis,
                        root_midis=root_midis,
                        third_fifth=third_fifth,
                        scale=scale,
                        prev=prev,
                        avoid_pcs=set(),
                        max_leap=cap,
                        rng=rng,
                        bar_start=True,
                        density=density,
                        variance=variance,
                    )
                    anchor = pitch
                elif i < len(motif_pitches):
                    src = motif_pitches[i] - motif_pitches[0]
                    if invert:
                        src = -src
                    target = (anchor if anchor is not None else lo + 7) + src
                    target = max(lo, min(hi, target))
                    pitch = _snap_contour(
                        target,
                        s,
                        chord_midis=chord_midis,
                        scale=scale,
                        prev=prev,
                        lo=lo,
                        hi=hi,
                        max_leap=cap,
                    )
                else:
                    pitch = first_pitch(bar, s)
            if pitch is None:
                pitch = lo
            place(bar, s, note_len, pitch)
            prev = pitch
            written.append(pitch)
        if out[bar * STEPS_PER_BAR] is None and (root_midis or chord_midis):
            cap = None if prev is None else 7
            pitch = _pick_near(
                _bar_start_pool(
                    root_midis,
                    third_fifth,
                    chord_midis,
                    prev,
                    cap,
                    avoid_pcs if bar == 0 else set(),
                    variance=variance,
                    rng=rng,
                )
                or chord_midis,
                prev,
                avoid_pcs=avoid_pcs if bar == 0 else None,
                max_leap=cap,
                rng=rng,
            )
            if pitch is not None:
                place(bar, 0, 4 if phrase == "hook_hold" else 2, pitch)
                if prev is None:
                    prev = pitch
                if not written:
                    written.append(pitch)
        return written

    def replay_pitches() -> bool:
        return variance <= 0.0 or (variance < 1.0 and rng.random() >= variance)

    if phrase == "hook_hold":
        hits = _apply_density(_HOOK_SEQUENCE, density, rng)
        lengths = _hit_lengths(hits, rng, long_ok=True, length=length)
        if length >= 0.45:
            for i, s in enumerate(hits):
                nxt = hits[i + 1] if i + 1 < len(hits) else STEPS_PER_BAR
                room = max(1, nxt - s)
                if room >= 8 and lengths[i] < 8:
                    lengths[i] = 8
                    break
        motif = stamp_hits(0, hits, lengths)
        for bar in range(1, BARS):
            stamp_hits(
                bar,
                hits,
                lengths,
                motif_pitches=motif if replay_pitches() else None,
            )
    elif phrase == "sparse_pickup":
        hits = _apply_density(_PICKUP_SEQUENCE, density, rng)
        lengths = _hit_lengths(hits, rng, long_ok=length > 0.4, length=length)
        last_len = 16 if length >= 0.75 else (4 if length <= 0.3 else 8)
        motif = stamp_hits(0, hits, lengths)
        for bar in range(1, BARS):
            if bar == BARS - 1:
                stamp_hits(bar, [0], [last_len])
                continue
            stamp_hits(
                bar,
                hits,
                lengths,
                motif_pitches=motif if replay_pitches() else None,
            )
    else:
        hits = _apply_density(_pick_motif(rng, density), density, rng)
        lengths = _hit_lengths(hits, rng, long_ok=True, length=length)
        motif = stamp_hits(0, hits, lengths)
        if not motif:
            motif = stamp_hits(0, [0], [8])
            hits, lengths = [0], [8]
        invert_from = 2 if phrase == "call_answer" else 99
        if variance >= 0.85:
            invert_from = min(invert_from, 1)
        for bar in range(1, BARS):
            stamp_hits(
                bar,
                hits,
                lengths,
                invert=bar >= invert_from,
                motif_pitches=motif if replay_pitches() else None,
            )

    if density < 0.8:
        _ensure_rest(out, rng)
    return _midi_state(pattern_id=f"prog-lead-{phrase}", octave=octv, key=minor_key, grid=out)


def apply_key(progression: dict[str, Any], key: str) -> dict[str, Any]:
    """Same recipe (or romans), new tonic, still Aeolian. Keeps locked."""
    if not isinstance(progression, dict) or not progression:
        raise ValueError("progression required")
    rid = progression.get("recipe_id")
    chords = progression.get("chords") or []
    romans = [
        str(c.get("roman") or "i")
        for c in chords
        if isinstance(c, dict)
    ]
    rec = RECIPES.get(rid) if rid in RECIPES else None
    if rec and len(romans) == BARS and list(rec["romans"]) == romans:
        recipe: str | dict[str, Any] = rid
    elif len(romans) == BARS:
        recipe = {
            "id": "custom",
            "label": progression.get("label") or "–".join(romans),
            "romans": romans,
            "pad_seventh": bool(progression.get("pad_seventh")),
        }
    elif rec:
        recipe = rid
    else:
        raise ValueError("progression must have 4 chords")
    out = realize(recipe, key)
    out["locked"] = bool(progression.get("locked"))
    out["style_used"] = progression.get("style_used") or ""
    if progression.get("diced_at"):
        out["diced_at"] = progression["diced_at"]
    src_chords = progression.get("chords") or []
    for i, c in enumerate(out["chords"]):
        prev = src_chords[i] if i < len(src_chords) and isinstance(src_chords[i], dict) else {}
        c["enabled"] = chord_enabled(prev) if prev else True
    return out


def validate_progression(doc: dict[str, Any]) -> dict[str, Any]:
    """Accept a 4-bar theme. Unknown recipe_id is ok when chords is length 4."""
    if not isinstance(doc, dict) or not doc:
        raise ValueError("progression required")
    bars = doc.get("bars")
    if bars is not None and int(bars) != BARS:
        raise ValueError("progression bars must be 4")
    chords = doc.get("chords")
    if chords is not None:
        if not isinstance(chords, list) or len(chords) != BARS:
            raise ValueError("progression bars must be 4")
    elif doc.get("recipe_id") not in RECIPES:
        raise ValueError("progression bars must be 4")
    out = dict(doc)
    out["bars"] = BARS
    return out


def reconcile_progression(
    doc: dict[str, Any] | None, key: str
) -> dict[str, Any] | None:
    """Force bars=4 and respell to `key`'s tonic (still Aeolian)."""
    if not doc:
        return None
    return apply_key(validate_progression(doc), key)


def _track_midi(track: dict[str, Any]) -> dict[str, Any] | None:
    midi = track.get("midi")
    return midi if isinstance(midi, dict) else None


def _track_octave(track: dict[str, Any], default: int) -> int:
    if track.get("octave") is not None:
        return int(track["octave"])
    midi = _track_midi(track)
    if midi is not None and midi.get("octave") is not None:
        return int(midi["octave"])
    return int(default)


def _validate_track_grids(tracks: list[dict[str, Any]]) -> None:
    if len(tracks) > 32:
        raise ValueError("too many tracks")
    for track in tracks:
        midi = _track_midi(track) if isinstance(track, dict) else None
        if not midi:
            continue
        grid = midi.get("grid")
        if grid is None:
            continue
        if not isinstance(grid, list) or len(grid) not in (STEPS_PER_BAR, LOOP_STEPS):
            raise ValueError("grid length must be 16 or 64")


def rewrite_bass_pad(
    progression: dict[str, Any],
    tracks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Rewrite bass roots + pad voicings. Lead is untouched."""
    midi_out: dict[str, Any] = {}
    for track in tracks:
        if not isinstance(track, dict):
            continue
        tid = str(track.get("id") or "").strip()
        if not tid:
            continue
        role = harmony_role(track.get("type") or tid)
        if role == "bass":
            midi_out[tid] = rewrite_bass_grid(
                progression,
                _track_midi(track),
                octave=_track_octave(track, 2),
            )
        elif role == "pad":
            midi_out[tid] = rewrite_pad_grid(
                progression,
                octave=_track_octave(track, 3),
            )
    return midi_out


def _restamp_lead(
    midi: dict[str, Any],
    progression: dict[str, Any],
    octave: int,
) -> dict[str, Any]:
    """Keep a progression-source lead grid; restamp Aeolian key."""
    grid = midi.get("grid")
    if isinstance(grid, list):
        grid = list(grid)
    bars = (
        BARS
        if midi.get("bars") == BARS
        or (isinstance(grid, list) and len(grid) == LOOP_STEPS)
        else (midi.get("bars") or 1)
    )
    return {
        "patternId": midi.get("patternId") or "prog-lead",
        "octave": int(octave),
        "key": progression.get("key") or tonic_minor_label(""),
        "bars": bars,
        "source": "progression",
        "locked": bool(midi.get("locked")),
        "grid": grid,
    }


def dice_chords(
    *,
    key: str,
    style: str = "",
    tracks: list[dict[str, Any]] | None = None,
    avoid_recipe_id: str | None = None,
    density: float = 0.5,
    variance: float = 0.5,
    length: float = 0.5,
    seed: int | None = None,
) -> dict[str, Any]:
    """Pick a recipe, realize Aeolian, write bass runner + pad voicings."""
    tracks = list(tracks or [])
    _validate_track_grids(tracks)
    rec = pick_recipe(style, avoid=avoid_recipe_id)
    prog = realize(rec, key)
    prog["style_used"] = (style or "").strip()
    prog["diced_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    midi_out: dict[str, Any] = {}
    for track in tracks:
        if not isinstance(track, dict):
            continue
        tid = str(track.get("id") or "").strip()
        if not tid:
            continue
        role = harmony_role(track.get("type") or tid)
        if role == "bass":
            midi_out[tid] = dice_bass_grid(
                prog,
                octave=_track_octave(track, 2),
                density=track.get("density", density),
                variance=track.get("variance", variance),
                length=track.get("length", length),
                seed=seed,
            )
        elif role == "pad":
            midi_out[tid] = rewrite_pad_grid(
                prog,
                octave=_track_octave(track, 3),
            )
    return {"progression": prog, "midi": midi_out}


def apply_harmony(
    *,
    key: str,
    progression: dict[str, Any],
    tracks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Respell the same recipe at a new tonic. Rewrites bass/pad; lead if source=progression."""
    tracks = list(tracks or [])
    if not isinstance(progression, dict) or not progression:
        raise ValueError("progression required")
    bars = progression.get("bars")
    if bars is not None and int(bars) != BARS:
        raise ValueError("progression bars must be 4")
    chords = progression.get("chords")
    if chords is not None and (not isinstance(chords, list) or len(chords) != BARS):
        raise ValueError("progression bars must be 4")
    _validate_track_grids(tracks)
    prog = apply_key(progression, key)
    midi_out = rewrite_bass_pad(prog, tracks)
    for track in tracks:
        if not isinstance(track, dict):
            continue
        tid = str(track.get("id") or "").strip()
        if not tid:
            continue
        if harmony_role(track.get("type") or tid) != "lead":
            continue
        midi = _track_midi(track)
        if not midi or midi.get("source") != "progression":
            continue
        midi_out[tid] = _restamp_lead(midi, prog, _track_octave(track, 4))
    return {"progression": prog, "midi": midi_out}


def dice_bass(
    *,
    key: str,
    progression: dict[str, Any],
    tracks: list[dict[str, Any]] | None = None,
    seed: int | None = None,
    density: float = 0.5,
    variance: float = 0.5,
    length: float = 0.5,
) -> dict[str, Any]:
    """Rewrite bass-role MIDI over the current progression. Does not mutate it."""
    tracks = list(tracks or [])
    if not isinstance(progression, dict) or not progression:
        raise ValueError("progression required")
    bars = progression.get("bars")
    if bars is not None and int(bars) != BARS:
        raise ValueError("progression bars must be 4")
    chords = progression.get("chords")
    if not isinstance(chords, list) or len(chords) != BARS:
        raise ValueError("progression bars must be 4")
    _validate_track_grids(tracks)
    midi_out: dict[str, Any] = {}
    for track in tracks:
        if not isinstance(track, dict):
            continue
        tid = str(track.get("id") or "").strip()
        if not tid:
            continue
        if harmony_role(track.get("type") or tid) != "bass":
            continue
        midi_out[tid] = dice_bass_grid(
            progression,
            octave=_track_octave(track, 2),
            density=track.get("density", density),
            variance=track.get("variance", variance),
            length=track.get("length", length),
            seed=seed,
        )
    return {"midi": midi_out}


def dice_lead(
    *,
    key: str,
    progression: dict[str, Any],
    tracks: list[dict[str, Any]] | None = None,
    seed: int | None = None,
    density: float = 0.5,
    variance: float = 0.5,
    length: float = 0.5,
) -> dict[str, Any]:
    """Rewrite lead-role MIDI over the current progression. Does not mutate it."""
    tracks = list(tracks or [])
    if not isinstance(progression, dict) or not progression:
        raise ValueError("progression required")
    bars = progression.get("bars")
    if bars is not None and int(bars) != BARS:
        raise ValueError("progression bars must be 4")
    chords = progression.get("chords")
    if not isinstance(chords, list) or len(chords) != BARS:
        raise ValueError("progression bars must be 4")
    _validate_track_grids(tracks)
    midi_out: dict[str, Any] = {}
    for track in tracks:
        if not isinstance(track, dict):
            continue
        tid = str(track.get("id") or "").strip()
        if not tid:
            continue
        if harmony_role(track.get("type") or tid) != "lead":
            continue
        midi_out[tid] = dice_lead_grid(
            progression,
            key,
            seed=seed,
            octave=_track_octave(track, 4),
            avoid=_track_midi(track),
            density=track.get("density", density),
            variance=track.get("variance", variance),
            length=track.get("length", length),
        )
    return {"midi": midi_out}
