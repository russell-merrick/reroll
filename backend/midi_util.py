"""Grid → MIDI notes + .mid file write (no DawDreamer / numpy)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MAJOR = [0, 2, 4, 5, 7, 9, 11]
MINOR = [0, 2, 3, 5, 7, 8, 10]


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


def degree_to_midi(key: str, degree: int, octave: int = 3) -> int:
    root, quality = parse_key(key)
    ints = MAJOR if quality == "major" else MINOR
    d = int(degree) % 7
    return (int(octave) + 1) * 12 + root + ints[d]


def grid_to_notes(
    grid: list[dict | None] | None,
    *,
    key: str = "F minor",
    octave: int = 3,
    bars: int = 4,
) -> list[dict[str, Any]]:
    """Convert monophonic 16-step degree grid → beat-based notes."""
    if not grid:
        return []
    notes: list[dict[str, Any]] = []
    steps = len(grid) or 16
    for bar in range(max(1, int(bars))):
        for s, cell in enumerate(grid):
            if not cell or not isinstance(cell, dict):
                continue
            degree = int(cell.get("degree", 0))
            length = max(1, int(cell.get("length", 1)))
            vel = int(cell.get("vel", 100))
            step = bar * steps + s
            start_beat = step / 4.0
            dur_beats = max(0.05, length / 4.0)
            notes.append(
                {
                    "midi": degree_to_midi(key, degree, octave),
                    "start_beat": start_beat,
                    "duration_beats": dur_beats,
                    "velocity": max(1, min(127, vel)),
                }
            )
    return notes


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
