"""Grid → MIDI notes + .mid file write (no DawDreamer / numpy)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MAJOR = [0, 2, 4, 5, 7, 9, 11]
MINOR = [0, 2, 3, 5, 7, 8, 10]
STEPS_PER_BAR = 16


def parse_key(key: str) -> tuple[int, str]:
    raw = (key or "C minor").strip()
    m = re.match(r"([A-G])(#|b)?\s*(major|minor|maj|min)?", raw, re.I)
    if not m:
        return 0, "minor"
    name = m.group(1).upper() + (m.group(2) or "")
    flat_map = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}
    if name in flat_map:
        name = flat_map[name]
    root = NOTE_NAMES.index(name) if name in NOTE_NAMES else 0
    q = (m.group(3) or "minor").lower()
    quality = "major" if q in ("major", "maj") else "minor"
    return root, quality


# Splice-style key tokens in sample names: _Fm_, _G#min, _Bm, _C, …
_NOTE_ROOT: dict[str, int] = {
    "C": 0,
    "C#": 1,
    "DB": 1,
    "D": 2,
    "D#": 3,
    "EB": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "GB": 6,
    "G": 7,
    "G#": 8,
    "AB": 8,
    "A": 9,
    "A#": 10,
    "BB": 10,
    "B": 11,
}

# Prefer explicit quality (min/maj); then bare note tokens near end of stem.
_KEY_WITH_QUAL_RE = re.compile(
    r"(?:^|[^A-Za-z0-9])"
    r"([A-G])([#b]|sharp|flat)?"
    r"[-_\s]?(maj(?:or)?|min(?:or)?|m)"
    r"(?=[^A-Za-z0-9]|$)",
    re.I,
)
_KEY_BARE_RE = re.compile(
    r"(?:^|[^A-Za-z0-9])"
    r"([A-G])([#b]|sharp|flat)?"
    r"(?=[^A-Za-z0-9]|$)",
    re.I,
)


def _note_token_to_root(letter: str, acc: str | None) -> int | None:
    a = (acc or "").lower()
    if a in ("sharp", "#"):
        suffix = "#"
    elif a in ("flat", "b"):
        suffix = "b"
    else:
        suffix = ""
    key = ((letter or "").upper() + suffix).upper()  # Db → DB, C# → C#
    return _NOTE_ROOT.get(key)


def parse_key_from_name(name: str) -> tuple[int, str] | None:
    """
    Detect root key from a sample filename/path label (Splice-style).

    Returns (root_pc 0–11, quality) or None if no reliable key token.
    Quality is best-effort; many packs only tag the root note.
    """
    raw = str(name or "")
    # Prefer basename — pack folder names often contain stray letters
    stem = raw.replace("\\", "/").split("/")[-1]
    stem = re.sub(r"\.(wav|aif|aiff|flac|mp3|ogg)$", "", stem, flags=re.I)

    def _from_parts(letter: str, acc: str | None, qual_raw: str) -> tuple[int, str] | None:
        root = _note_token_to_root(letter, acc)
        if root is None:
            return None
        q = (qual_raw or "").lower()
        if q in ("maj", "major"):
            quality = "major"
        elif q in ("min", "minor", "m"):
            quality = "minor"
        else:
            quality = "minor"  # default label; transpose uses root only
        return root, quality

    with_qual = list(_KEY_WITH_QUAL_RE.finditer(stem))
    if with_qual:
        m = with_qual[-1]
        parsed = _from_parts(m.group(1), m.group(2), m.group(3) or "")
        if parsed:
            return parsed

    bare = list(_KEY_BARE_RE.finditer(stem))
    if not bare:
        return None
    # Prefer last token (packs put key near the end)
    m = bare[-1]
    return _from_parts(m.group(1), m.group(2), "")


def semitones_between_roots(from_root: int, to_root: int) -> int:
    """Shortest signed semitone distance in (-6, +6]."""
    d = (int(to_root) - int(from_root)) % 12
    if d > 6:
        d -= 12
    return d


def transpose_semitones_from_name(name: str, session_key: str) -> int | None:
    """
    Semitones to shift a sample so its labeled root matches session_key root.
    None if the filename has no parseable key.
    """
    detected = parse_key_from_name(name)
    if not detected:
        return None
    src_root, _ = detected
    dst_root, _ = parse_key(session_key)
    return semitones_between_roots(src_root, dst_root)


def pitch_ratio_from_semitones(semitones: float) -> float:
    return float(2.0 ** (float(semitones) / 12.0))


def degree_to_midi(key: str, degree: int, octave: int = 3, alter: int = 0) -> int:
    root, quality = parse_key(key)
    ints = MAJOR if quality == "major" else MINOR
    d = int(degree) % 7
    return (int(octave) + 1) * 12 + root + ints[d] + int(alter or 0)


def expand_bars(grid: list | None, bars: int) -> int:
    n = len(grid) if grid is not None else 0
    n = n or 16
    if n == int(bars) * STEPS_PER_BAR:
        return 1  # already a full-loop grid
    return max(1, int(bars))


def cell_voices(cell: dict) -> list[dict]:
    if isinstance(cell.get("voices"), list) and cell["voices"]:
        return cell["voices"]
    out: dict[str, Any] = {
        "degree": cell.get("degree", 0),
        "alter": cell.get("alter", 0),
        "vel": cell.get("vel", 100),
    }
    if cell.get("oct") is not None:
        out["oct"] = cell["oct"]
    return [out]


def grid_to_notes(
    grid: list[dict | None] | None,
    *,
    key: str = "F minor",
    octave: int = 3,
    bars: int = 4,
) -> list[dict[str, Any]]:
    """Convert degree grid → beat notes. A bars*16 grid is not tiled again."""
    if not grid:
        return []
    notes: list[dict[str, Any]] = []
    steps = len(grid)
    for bar in range(expand_bars(grid, bars)):
        for s, cell in enumerate(grid):
            if not cell or not isinstance(cell, dict):
                continue
            length = max(1, int(cell.get("length", 1)))
            start_beat = (bar * steps + s) / 4.0
            dur_beats = max(0.05, length / 4.0)
            for voice in cell_voices(cell):
                if not isinstance(voice, dict):
                    continue
                deg = int(voice.get("degree", cell.get("degree", 0)))
                octv = voice.get("oct", cell.get("oct", octave))
                alter = int(voice.get("alter", cell.get("alter", 0)) or 0)
                vel = int(voice.get("vel", cell.get("vel", 100)))
                notes.append(
                    {
                        "midi": degree_to_midi(key, deg, int(octv), alter=alter),
                        "start_beat": start_beat,
                        "duration_beats": dur_beats,
                        "velocity": max(1, min(127, vel)),
                    }
                )
    return notes


BAR_BEATS = 4.0


def _note_tile_sig(note: dict[str, Any]) -> tuple[int, float, float, int]:
    start = float(note.get("start_beat") or 0.0)
    return (
        int(note["midi"]),
        round(start % BAR_BEATS, 5),
        round(float(note.get("duration_beats") or 0.0), 5),
        int(note.get("velocity", note.get("vel", 100))),
    )


def collapse_tiled_bar_notes(
    notes: list[dict[str, Any]] | None,
    bars: int,
    *,
    bar_beats: float = BAR_BEATS,
) -> list[dict[str, Any]] | None:
    """
    If `notes` is a 1-bar phrase repeated `bars` times, return the first bar.

    Used so Serum only bounces 1 bar (then the audio is tiled). Returns None
    when the phrase is not periodic — e.g. a 4-bar chord cycle — so the caller
    must render the full length.
    """
    n_bars = max(1, int(bars))
    if n_bars <= 1 or not notes:
        return None
    first = [n for n in notes if float(n.get("start_beat") or 0.0) < bar_beats - 1e-6]
    if not first:
        return None
    # A note that rings across the bar line would be cut by a 1-bar bounce.
    slop = bar_beats / 16.0
    for n in first:
        start = float(n.get("start_beat") or 0.0)
        dur = float(n.get("duration_beats") or 0.0)
        if start + dur > bar_beats + slop:
            return None
    first_counts: dict[tuple[int, float, float, int], int] = {}
    for n in first:
        sig = _note_tile_sig(n)
        first_counts[sig] = first_counts.get(sig, 0) + 1
    all_counts: dict[tuple[int, float, float, int], int] = {}
    loop_end = n_bars * bar_beats
    for n in notes:
        start = float(n.get("start_beat") or 0.0)
        if start < -1e-6 or start >= loop_end - 1e-6:
            return None
        sig = _note_tile_sig(n)
        if sig not in first_counts:
            return None
        all_counts[sig] = all_counts.get(sig, 0) + 1
    for sig, c0 in first_counts.items():
        if all_counts.get(sig, 0) != c0 * n_bars:
            return None
    return first


def write_midi_file(
    path: Path | str,
    notes: list[dict[str, Any]],
    *,
    bpm: float = 140.0,
    track_name: str = "loop",
) -> Path:
    """Write a Type-0/1 MIDI file with one track of note on/off events."""
    import mido

    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("track_name", name=str(track_name)[:32], time=0))
    tr.append(
        mido.MetaMessage(
            "set_tempo",
            tempo=mido.bpm2tempo(max(20.0, min(300.0, float(bpm)))),
            time=0,
        )
    )

    # Absolute times in ticks, then convert to delta
    events: list[tuple[int, int, int, int]] = []  # (tick, priority, note, vel) vel=0 → off
    tpb = mid.ticks_per_beat
    for n in notes:
        start = float(n.get("start_beat", 0))
        dur = max(0.05, float(n.get("duration_beats", 0.25)))
        midi = int(n.get("midi", 60))
        vel = max(1, min(127, int(n.get("velocity", n.get("vel", 100)))))
        t0 = int(round(start * tpb))
        t1 = int(round((start + dur) * tpb))
        if t1 <= t0:
            t1 = t0 + 1
        events.append((t0, 0, midi, vel))  # note on first at same tick
        events.append((t1, 1, midi, 0))  # note off

    events.sort(key=lambda e: (e[0], e[1], e[2]))
    cursor = 0
    for tick, _pri, midi, vel in events:
        delta = max(0, tick - cursor)
        cursor = tick
        if vel > 0:
            tr.append(mido.Message("note_on", note=midi, velocity=vel, time=delta))
        else:
            tr.append(mido.Message("note_off", note=midi, velocity=0, time=delta))

    tr.append(mido.MetaMessage("end_of_track", time=0))
    mid.save(str(dest))
    return dest
