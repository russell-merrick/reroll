"""Harmony recipes, Aeolian realize, bass/pad/lead grids."""

from __future__ import annotations

from fastapi import HTTPException

from backend.app import (
    ApplyHarmonyRequest,
    DiceChordsRequest,
    api_dice_chords,
    api_harmony_apply,
    api_harmony_recipes,
)
from backend.harmony import (
    RECIPES,
    _style_recipe_weights,
    apply_harmony,
    apply_key,
    dice_chords,
    dice_lead_grid,
    harmony_role,
    pick_recipe,
    realize,
    rewrite_bass_grid,
    rewrite_pad_grid,
    tonic_minor_label,
)
from backend.midi_util import degree_to_midi, grid_to_notes


def test_eight_recipes():
    assert len(RECIPES) == 8
    assert list(RECIPES) == [
        "i_VI_III_VII",
        "i_VII_VI_VII",
        "pedal_i",
        "i_iv_VI_V",
        "i_VI_iv_V",
        "i_III_VI_VII",
        "i_v_VI_VII",
        "i_VI_i_VII",
    ]


def test_harmony_role():
    assert harmony_role("bass") == "bass"
    assert harmony_role("bass__2") == "bass"
    assert harmony_role("pad") == "pad"
    assert harmony_role("strings") == "pad"
    assert harmony_role("keys") == "pad"
    assert harmony_role("lead") == "lead"
    assert harmony_role("arp") == "lead"
    assert harmony_role("kick") is None
    assert harmony_role("lead_audio") is None
    assert harmony_role("bass_audio") is None


def test_tonic_minor_label():
    assert tonic_minor_label("F major") == "F minor"
    assert tonic_minor_label("F minor") == "F minor"
    assert tonic_minor_label("C# maj") == "C# minor"


def test_f_minor_i_VI_III_VII_roots():
    # F, Db, Ab, Eb
    prog = realize("i_VI_III_VII", "F minor")
    assert [c["root_pc"] for c in prog["chords"]] == [5, 1, 8, 3]
    assert [c["roman"] for c in prog["chords"]] == ["i", "VI", "III", "VII"]
    assert prog["key"] == "F minor"


def test_realize_ignores_major_quality():
    major = realize("i_VI_III_VII", "F major")
    minor = realize("i_VI_III_VII", "F minor")
    assert [c["pcs"] for c in major["chords"]] == [c["pcs"] for c in minor["chords"]]
    assert major["key"] == minor["key"] == "F minor"
    assert [c["root_pc"] for c in major["chords"]] == [5, 1, 8, 3]


def test_major_v_leading_tone():
    prog = realize("i_iv_VI_V", "F minor")
    v = prog["chords"][3]
    assert v["roman"] == "V"
    assert v["quality"] == "maj"
    assert v["pcs"] == [0, 4, 7]
    assert v["alters"].get("6") == 1


def test_pedal_i_same_root():
    prog = realize("pedal_i", "F minor")
    roots = [c["root_pc"] for c in prog["chords"]]
    assert len(set(roots)) == 1
    assert roots[0] == 5


def test_style_weights_prefer_prog_house():
    weights = _style_recipe_weights("prog house")
    assert weights["i_iv_VI_V"] == max(weights.values())
    assert weights["i_iv_VI_V"] > weights["pedal_i"]


def test_pick_recipe_avoids():
    for _ in range(40):
        rec = pick_recipe("prog house", avoid="i_iv_VI_V")
        assert rec["id"] != "i_iv_VI_V"
        assert rec["id"] in RECIPES


def test_rewrite_bass_64_roots():
    prog = realize("i_VI_III_VII", "F minor")
    midi = rewrite_bass_grid(prog, octave=2)
    assert len(midi["grid"]) == 64
    assert midi["bars"] == 4
    assert midi["patternId"] == "prog-roots"
    assert midi["source"] == "progression"
    for bar, chord in enumerate(prog["chords"]):
        cell = midi["grid"][bar * 16]
        assert cell is not None
        assert cell["degree"] == chord["root_degree"]
        assert "voices" not in cell


def test_pad_sevenths_only_on_two_recipes():
    for rid in RECIPES:
        prog = realize(rid, "F minor")
        midi = rewrite_pad_grid(prog, octave=3)
        cell = midi["grid"][0]
        assert cell is not None
        n = len(cell["voices"])
        if rid in ("i_VI_III_VII", "i_iv_VI_V"):
            assert n == 4
        else:
            assert n == 3


def _lead_notes(midi: dict, octave: int) -> list[dict]:
    notes = grid_to_notes(midi["grid"], key=midi["key"], octave=octave, bars=4)
    return sorted(notes, key=lambda n: n["start_beat"])


def test_dice_lead_octave_5_ninth():
    prog = realize("i_VI_III_VII", "C major")
    for seed in range(8):
        midi = dice_lead_grid(prog, "C major", seed=seed, octave=5)
        assert len(midi["grid"]) == 64
        assert midi["key"] == "C minor"
        notes = _lead_notes(midi, 5)
        assert notes
        # C5–D6
        assert all(72 <= n["midi"] <= 86 for n in notes)
        lo = degree_to_midi(midi["key"], 0, 5)
        assert lo == 72
        assert all(lo <= n["midi"] <= lo + 14 for n in notes)


def test_dice_lead_leaps_capped_after_first():
    prog = realize("i_VI_III_VII", "F minor")
    for seed in range(50):
        midi = dice_lead_grid(prog, "F minor", seed=seed, octave=5)
        notes = _lead_notes(midi, 5)
        assert notes
        for a, b in zip(notes, notes[1:]):
            assert abs(b["midi"] - a["midi"]) <= 7, (seed, a["midi"], b["midi"])


def test_dice_lead_avoid_moves_bar_start():
    prog = realize("i_VI_III_VII", "F minor")
    avoid = [5, 1, 8, 3]  # i–VI–III–VII roots
    midi = dice_lead_grid(prog, "F minor", seed=0, octave=5, avoid=avoid)
    notes = _lead_notes(midi, 5)
    bar0 = [n for n in notes if n["start_beat"] == 0.0]
    assert bar0
    assert bar0[0]["midi"] % 12 != 5


def test_apply_key_keeps_recipe_and_locked():
    prog = realize("i_VI_III_VII", "F minor")
    prog["locked"] = True
    prog["style_used"] = "Melodic Techno"
    out = apply_key(prog, "C major")
    assert out["recipe_id"] == "i_VI_III_VII"
    assert out["locked"] is True
    assert out["key"] == "C minor"
    assert [c["root_pc"] for c in out["chords"]] == [0, 8, 3, 10]


def test_f_major_session_bass_vi_is_db_not_d():
    """Hear-it: #key = F major → returned bass midi.key is F minor; VI root is Db (49)."""
    out = dice_chords(
        key="F major",
        style="melodic techno",
        tracks=[{"id": "bass", "type": "bass", "octave": 2}],
        avoid_recipe_id="pedal_i",
    )
    bass = out["midi"]["bass"]
    assert bass["key"] == "F minor"
    assert out["progression"]["key"] == "F minor"
    notes = grid_to_notes(bass["grid"], key=bass["key"], octave=2, bars=4)
    vi_bars = [c["bar"] for c in out["progression"]["chords"] if c["roman"] == "VI"]
    assert vi_bars, out["progression"]["recipe_id"]
    for bar in vi_bars:
        bar_notes = [n for n in notes if bar * 4.0 <= n["start_beat"] < (bar + 1) * 4.0]
        assert bar_notes
        assert bar_notes[0]["midi"] == 49  # Db2
        assert all(n["midi"] != 50 for n in bar_notes)


def test_apply_rewrites_bass_not_user_lead():
    prog = realize("i_VI_III_VII", "F minor")
    lead_grid = [{"degree": 0, "length": 2, "vel": 100}] + [None] * 63
    result = apply_harmony(
        key="C major",
        progression=prog,
        tracks=[
            {"id": "bass", "type": "bass", "octave": 2},
            {
                "id": "lead",
                "type": "lead",
                "octave": 4,
                "midi": {
                    "source": "user",
                    "key": "F minor",
                    "bars": 4,
                    "grid": lead_grid,
                },
            },
            {
                "id": "lead2",
                "type": "lead",
                "octave": 4,
                "midi": {
                    "source": "progression",
                    "key": "F minor",
                    "bars": 4,
                    "patternId": "prog-lead",
                    "grid": lead_grid,
                },
            },
        ],
    )
    assert "bass" in result["midi"]
    assert "lead" not in result["midi"]
    assert result["midi"]["lead2"]["key"] == "C minor"
    assert result["midi"]["lead2"]["source"] == "progression"
    assert result["progression"]["key"] == "C minor"


def test_recipes_endpoint_lists_eight():
    out = api_harmony_recipes()
    assert out["ok"] is True
    assert out["loop_bars"] == 4
    assert len(out["recipes"]) == 8


def test_dice_chords_locked_409():
    try:
        api_dice_chords(DiceChordsRequest(locked=True, tracks=[]))
        raise AssertionError("expected 409")
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail == "theme locked"


def test_apply_rejects_wrong_bars():
    try:
        api_harmony_apply(
            ApplyHarmonyRequest(
                key="F minor",
                progression={"recipe_id": "i_VI_III_VII", "bars": 8, "chords": []},
                tracks=[],
            )
        )
        raise AssertionError("expected 400")
    except HTTPException as exc:
        assert exc.status_code == 400
