"""MIDI grid → beat notes (must align with kick 16th grid)."""

from __future__ import annotations

from host.renderer import grid_to_notes
from backend.timing import LOOP_BARS, sec_per_16th


def _quarter_grid() -> list[dict | None]:
    grid: list[dict | None] = [None] * 16
    for s in (0, 4, 8, 12):
        grid[s] = {"degree": 0, "length": 1, "vel": 100}
    return grid


def test_quarter_hits_map_to_integer_beats():
    notes = grid_to_notes(_quarter_grid(), key="F minor", octave=2, bars=1)
    starts = sorted(n["start_beat"] for n in notes)
    assert starts == [0.0, 1.0, 2.0, 3.0]


def test_expand_to_loop_bars():
    notes = grid_to_notes(_quarter_grid(), key="F minor", octave=2, bars=LOOP_BARS)
    # 4 quarters × 4 bars
    assert len(notes) == 16
    # Last bar first hit at beat 12
    starts = sorted(n["start_beat"] for n in notes)
    assert 12.0 in starts
    assert max(starts) == 15.0


def test_sixteenth_step_one_is_quarter_beat():
    grid: list[dict | None] = [None] * 16
    grid[1] = {"degree": 0, "length": 1, "vel": 100}
    notes = grid_to_notes(grid, key="C major", octave=4, bars=1)
    assert len(notes) == 1
    assert notes[0]["start_beat"] == 0.25  # one 16th


def test_duration_beats_from_length():
    grid: list[dict | None] = [None] * 16
    grid[0] = {"degree": 0, "length": 4, "vel": 100}  # one quarter note long
    notes = grid_to_notes(grid, key="C minor", octave=3, bars=1)
    assert notes[0]["duration_beats"] == 1.0


def test_note_times_in_seconds_at_bpm():
    """Beats → seconds conversion used by host (beats=True path still beat-based)."""
    notes = grid_to_notes(_quarter_grid(), key="F minor", octave=2, bars=1)
    bpm = 140.0
    spb = 60.0 / bpm
    # First note at t=0; second at one beat
    assert notes[0]["start_beat"] * spb == 0.0
    assert abs(notes[1]["start_beat"] * spb - spb) < 1e-9
    # One beat == 4 sixteenths
    assert abs(spb - 4 * sec_per_16th(bpm)) < 1e-9
