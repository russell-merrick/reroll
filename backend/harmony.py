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
}
_NO_STYLE = frozenset(
    {"", "none", "no preference", "nopreference", "any", "all", "random", "n/a", "na"}
)
_BASS_TYPES = frozenset({"bass"})
_PAD_TYPES = frozenset({"pad", "pads", "strings", "chorus", "keys"})
_LEAD_TYPES = frozenset(
    {"lead", "synth", "arp", "pluck", "seq", "hoover", "guitar", "brass"}
)
_LEAD_RHYTHMS: tuple[tuple[int, ...], ...] = (
    (0, 4, 8, 12),
    (0, 2, 4, 6, 8, 10, 12, 14),
    (0, 3, 6, 8, 11, 14),
)
_TONIC_RE = re.compile(r"([A-G])(#|b)?", re.I)


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


def _parse_roman(roman: str) -> tuple[int, str]:
    raw = (roman or "i").strip()
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


def _style_recipe_weights(style: str) -> dict[str, int]:
    weights = {rid: 1 for rid in RECIPES}
    blob = (style or "").strip().lower()
    if blob in _NO_STYLE:
        return weights
    melodic = any(t in blob for t in ("melodic", "afterlife"))
    prog = any(t in blob for t in ("prog", "progressive", "anjunadeep"))
    trance = any(t in blob for t in ("trance", "uplifting", "anjunabeats", "3.0"))
    techno = any(t in blob for t in ("techno", "peak", "hard")) and not melodic
    house = "house" in blob and not prog
    if melodic:
        weights["i_VI_III_VII"] *= 3
        weights["i_VII_VI_VII"] *= 2
        weights["i_III_VI_VII"] *= 2
    if prog:
        weights["i_iv_VI_V"] *= 3
        weights["i_VI_iv_V"] *= 2
    if trance:
        weights["i_VI_III_VII"] *= 3
        weights["i_VI_iv_V"] *= 2
        weights["i_III_VI_VII"] *= 2
    if techno:
        weights["pedal_i"] *= 2
        weights["i_VII_VI_VII"] *= 2
        weights["i_v_VI_VII"] *= 2
    if house:
        weights["i_iv_VI_V"] *= 2
        weights["i_VI_i_VII"] *= 2
    return weights


def pick_recipe(
    style: str = "",
    avoid: str | None = None,
    *,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Weighted recipe pick. Never returns `avoid` if another recipe exists."""
    picker = rng or random.Random()
    ids = list(RECIPES)
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


def rewrite_bass_grid(
    progression: dict[str, Any],
    grid: list | dict | None = None,
    *,
    octave: int | None = None,
) -> dict[str, Any]:
    """64-step roots-only bass. Rhythm from `grid` (bar 0 if already 64)."""
    chords = progression["chords"]
    key = progression.get("key") or "C minor"
    octv = 2 if octave is None else int(octave)
    rhythm = _rhythm_bar(grid)
    out = _empty_grid()
    for bar, chord in enumerate(chords[:BARS]):
        deg = int(chord["root_degree"])
        for s, src in enumerate(rhythm):
            if not src:
                continue
            out[bar * STEPS_PER_BAR + s] = {
                "degree": deg,
                "length": src["length"],
                "vel": src["vel"],
            }
    return _midi_state(pattern_id="prog-roots", octave=octv, key=key, grid=out)


def _close_midis(chord: dict[str, Any], octave: int, seventh: bool) -> list[int]:
    intervals = list(chord["intervals"])
    if seventh and 10 not in intervals:
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
        progression["chords"],
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


def _cell_from_midi(midi_n: int, key: str, length: int, vel: int = 100) -> dict[str, Any]:
    deg, octv, alter = _split_midi(midi_n, key)
    cell: dict[str, Any] = {
        "degree": deg,
        "length": max(1, int(length)),
        "vel": vel,
        "oct": octv,
    }
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


def _bar_start_pool(
    root_midis: list[int],
    third_fifth: list[int],
    chord_midis: list[int],
    prev: int | None,
    max_leap: int | None,
    avoid_pcs: set[int] | None,
) -> list[int]:
    """Root on s==0 only if it stays in the leap window and is not avoided."""
    roots = list(root_midis)
    others = list(third_fifth) if third_fifth else [m for m in chord_midis if m not in roots]
    if avoid_pcs and roots and all((m % 12) in avoid_pcs for m in roots):
        return others or chord_midis
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


def dice_lead_grid(
    progression: dict[str, Any],
    key: str,
    *,
    seed: int | None = None,
    octave: int | None = None,
    avoid: Any = None,
) -> dict[str, Any]:
    """Monophonic 64-step lead: chord tones on downbeats, Aeolian passing off."""
    minor_key = progression.get("key") or tonic_minor_label(key)
    octv = 4 if octave is None else int(octave)
    lo = degree_to_midi(minor_key, 0, octv)
    hi = lo + 14
    rng = random.Random(seed)
    scale = _scale_midis(minor_key, lo, hi)
    avoid_pcs = _avoid_pcs(avoid, minor_key)
    out = _empty_grid()
    prev: int | None = None
    for bar, chord in enumerate(progression["chords"][:BARS]):
        hits = list(rng.choice(_LEAD_RHYTHMS))
        chord_midis = _pcs_in_range(chord["pcs"], lo, hi)
        root_midis = _pcs_in_range([chord["root_pc"]], lo, hi)
        third_fifth = []
        if len(chord["pcs"]) >= 2:
            third_fifth.extend(_pcs_in_range([chord["pcs"][1]], lo, hi))
        if len(chord["pcs"]) >= 3:
            third_fifth.extend(_pcs_in_range([chord["pcs"][2]], lo, hi))
        if not third_fifth:
            third_fifth = list(chord_midis)
        for i, s in enumerate(hits):
            step = bar * STEPS_PER_BAR + s
            nxt = hits[i + 1] if i + 1 < len(hits) else STEPS_PER_BAR
            room = max(1, nxt - s)
            allow_leap = prev is None and bar == 0
            max_leap = None if allow_leap else 7
            pitch: int | None = None
            length = 1
            if s % 4 == 0:
                if s == 0:
                    pool = _bar_start_pool(
                        root_midis,
                        third_fifth,
                        chord_midis,
                        prev,
                        max_leap,
                        avoid_pcs,
                    )
                else:
                    pool = third_fifth or chord_midis
                pitch = _pick_near(
                    pool,
                    prev,
                    avoid_pcs=avoid_pcs,
                    max_leap=max_leap,
                    rng=rng,
                )
                hi_len = min(4, room)
                lo_len = min(2, hi_len)
                length = rng.randint(lo_len, hi_len)
            elif s % 2 == 0:
                if rng.random() < 0.65 and prev is not None:
                    pitch = _pick_near(
                        _neighbors(prev, scale),
                        prev,
                        max_leap=max_leap,
                        rng=rng,
                    )
                if pitch is None:
                    pitch = _pick_near(
                        chord_midis,
                        prev,
                        max_leap=max_leap,
                        rng=rng,
                    )
                length = rng.randint(1, min(2, room))
            else:
                if rng.random() >= 0.25:
                    continue
                if prev is not None:
                    pitch = _pick_near(
                        _neighbors(prev, scale),
                        prev,
                        max_leap=max_leap,
                        rng=rng,
                    )
                if pitch is None:
                    pitch = _pick_near(scale or chord_midis, prev, max_leap=max_leap, rng=rng)
                length = 1
            if pitch is None:
                continue
            out[step] = _cell_from_midi(pitch, minor_key, length, 100)
            prev = pitch
        # Guarantee a downbeat so a bar is never silent
        if out[bar * STEPS_PER_BAR] is None and (root_midis or chord_midis):
            cap = None if prev is None and bar == 0 else 7
            pitch = _pick_near(
                _bar_start_pool(
                    root_midis,
                    third_fifth,
                    chord_midis,
                    prev,
                    cap,
                    avoid_pcs,
                )
                or chord_midis,
                prev,
                avoid_pcs=avoid_pcs,
                max_leap=cap,
                rng=rng,
            )
            if pitch is not None:
                out[bar * STEPS_PER_BAR] = _cell_from_midi(pitch, minor_key, 2, 100)
                if prev is None:
                    prev = pitch
    return _midi_state(pattern_id="prog-lead", octave=octv, key=minor_key, grid=out)


def apply_key(progression: dict[str, Any], key: str) -> dict[str, Any]:
    """Same recipe (or romans), new tonic, still Aeolian. Keeps locked."""
    if not isinstance(progression, dict) or not progression:
        raise ValueError("progression required")
    rid = progression.get("recipe_id")
    if rid in RECIPES:
        recipe: str | dict[str, Any] = rid
    else:
        chords = progression.get("chords") or []
        romans = [
            str(c.get("roman") or "i")
            for c in chords
            if isinstance(c, dict)
        ]
        if len(romans) != BARS:
            raise ValueError("progression must have 4 chords")
        recipe = {
            "id": rid or "custom",
            "label": progression.get("label") or "–".join(romans),
            "romans": romans,
            "pad_seventh": bool(progression.get("pad_seventh")),
        }
    out = realize(recipe, key)
    out["locked"] = bool(progression.get("locked"))
    out["style_used"] = progression.get("style_used") or ""
    if progression.get("diced_at"):
        out["diced_at"] = progression["diced_at"]
    return out


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
) -> dict[str, Any]:
    """Pick a recipe, realize Aeolian, rewrite bass/pad MIDI."""
    tracks = list(tracks or [])
    _validate_track_grids(tracks)
    rec = pick_recipe(style, avoid=avoid_recipe_id)
    prog = realize(rec, key)
    prog["style_used"] = (style or "").strip()
    prog["diced_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"progression": prog, "midi": rewrite_bass_pad(prog, tracks)}


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


def dice_lead(
    *,
    key: str,
    progression: dict[str, Any],
    tracks: list[dict[str, Any]] | None = None,
    seed: int | None = None,
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
        )
    return {"midi": midi_out}
