"""MIDI grid helpers + .mid write."""

from __future__ import annotations

from pathlib import Path

from backend.midi_util import (
    collapse_tiled_bar_notes,
    degree_to_midi,
    grid_to_notes,
    parse_key_from_name,
    transpose_semitones_from_name,
    write_midi_file,
)


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


def test_collapse_tiled_quarters():
    grid: list[dict | None] = [None] * 16
    for s in (0, 4, 8, 12):
        grid[s] = {"degree": 0, "length": 2, "vel": 100}
    notes = grid_to_notes(grid, key="F minor", octave=2, bars=4)
    assert len(notes) == 16
    first = collapse_tiled_bar_notes(notes, 4)
    assert first is not None
    assert len(first) == 4
    assert [n["start_beat"] for n in first] == [0.0, 1.0, 2.0, 3.0]


def test_collapse_rejects_changing_harmony():
    # Four different roots — not a tiled 1-bar phrase
    notes = [
        {"midi": 41, "start_beat": 0.0, "duration_beats": 4.0, "velocity": 100},
        {"midi": 49, "start_beat": 4.0, "duration_beats": 4.0, "velocity": 100},
        {"midi": 44, "start_beat": 8.0, "duration_beats": 4.0, "velocity": 100},
        {"midi": 46, "start_beat": 12.0, "duration_beats": 4.0, "velocity": 100},
    ]
    assert collapse_tiled_bar_notes(notes, 4) is None


def test_collapse_rejects_note_hanging_past_bar():
    notes = []
    for bar in range(4):
        notes.append(
            {
                "midi": 41,
                "start_beat": bar * 4.0 + 3.5,
                "duration_beats": 1.5,
                "velocity": 100,
            }
        )
    assert collapse_tiled_bar_notes(notes, 4) is None


def test_write_midi_file(tmp_path: Path):
    notes = [
        {"midi": 60, "start_beat": 0.0, "duration_beats": 0.5, "velocity": 100},
        {"midi": 64, "start_beat": 1.0, "duration_beats": 0.5, "velocity": 90},
    ]
    dest = tmp_path / "t.mid"
    write_midi_file(dest, notes, bpm=140, track_name="test")
    assert dest.is_file()
    assert dest.stat().st_size > 20


def test_parse_key_from_name_splice_styles():
    cases = [
        ("KMRBI_BP_130_synth_lead_loop_phoney_Bm.wav", 11, "minor"),  # B
        ("BOS_EN_150_Synth_Lead_Loop_Supersonic_Dm.wav", 2, "minor"),  # D
        ("DS_HT_152_synth_lead_dark_main_F#min.wav", 6, "minor"),
        ("019_Short_Synth_Loop_138bpm_G#_-_138BPMT_Zenhiser.wav", 8, "minor"),
        ("808_oneshot_subby_pop_C.wav", 0, "minor"),
        ("FO4_DHT_140_synth_noise_G#maj.wav", 8, "major"),
        ("ESM_CR_126_fx_synth_loop_future_rave_old_dance_vibe_g#m.wav", 8, "minor"),
        ("PLX_ATT_140_kit_rise_chord_Emin.wav", 4, "minor"),
    ]
    for name, root, quality in cases:
        got = parse_key_from_name(name)
        assert got is not None, name
        assert got[0] == root, (name, got)
        assert got[1] == quality, (name, got)


def test_parse_key_from_name_no_false_positive():
    assert parse_key_from_name("MARS_808_clap_gated.wav") is None
    assert parse_key_from_name("plain_kick_oneshot.wav") is None


def test_transpose_semitones_from_name():
    # Bm (B=11) → F minor (F=5): shortest is +6 (tritone)
    assert transpose_semitones_from_name(
        "KMRBI_BP_130_synth_lead_loop_phoney_Bm.wav", "F minor"
    ) == 6
    # Dm (D=2) → F minor (F=5): +3
    assert transpose_semitones_from_name(
        "BOS_EN_150_Synth_Lead_Loop_Supersonic_Dm.wav", "F minor"
    ) == 3
    # Already F minor root
    assert transpose_semitones_from_name("lead_loop_Fm_128.wav", "F minor") == 0
    # No key tag
    assert transpose_semitones_from_name("kick_oneshot.wav", "F minor") is None
