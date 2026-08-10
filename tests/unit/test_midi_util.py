"""MIDI grid helpers + .mid write."""

from __future__ import annotations

from pathlib import Path

from backend.midi_util import degree_to_midi, grid_to_notes, write_midi_file


def test_degree_to_midi_f_minor_root():
    # F minor root at octave 2 → F2 = 41
    assert degree_to_midi("F minor", 0, 2) == 41


def test_grid_quarters():
    grid: list[dict | None] = [None] * 16
    for s in (0, 4, 8, 12):
        grid[s] = {"degree": 0, "length": 4, "vel": 100}
    notes = grid_to_notes(grid, key="F minor", octave=2, bars=1)
    assert len(notes) == 4
    assert notes[0]["start_beat"] == 0.0
    assert notes[1]["start_beat"] == 1.0
    assert notes[0]["duration_beats"] == 1.0


def test_write_midi_file(tmp_path: Path):
    notes = [
        {"midi": 60, "start_beat": 0.0, "duration_beats": 0.5, "velocity": 100},
        {"midi": 64, "start_beat": 1.0, "duration_beats": 0.5, "velocity": 90},
    ]
    dest = tmp_path / "t.mid"
    write_midi_file(dest, notes, bpm=140, track_name="test")
    assert dest.is_file()
    assert dest.stat().st_size > 20
