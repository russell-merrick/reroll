"""Harmony recipes, Aeolian realize, bass/pad/lead grids."""

from __future__ import annotations

from fastapi import HTTPException

from backend.app import (
    ApplyHarmonyRequest,
    DiceChordsRequest,
    DiceLeadRequest,
    api_dice_chords,
    api_dice_lead,
    api_harmony_apply,
    api_harmony_recipes,
)
from backend.harmony import (
    RECIPES,
    _MOTIF_RHYTHMS,
    _MOTIF_RHYTHMS_DENSE,
    _style_recipe_weights,
    apply_edited_harmony,
    apply_harmony,
    apply_key,
    chord_enabled,
    edit_chords,
    effective_chords,
    dice_bass_grid,
    dice_chords,
    dice_lead,
    dice_lead_grid,
    harmony_role,
    pc_to_degree_alter,
    is_two_cell_recipe,
    pick_recipe,
    recipe_unique_count,
    realize,
    rewrite_bass_grid,
    rewrite_pad_grid,
    tonic_minor_label,
)
from backend.midi_util import degree_to_midi, grid_to_notes


def test_recipe_table():
    assert set(RECIPES) >= {
        "i_VI_III_VII",
        "i_VII_VI_VII",
        "pedal_i",
        "i_iv_VI_V",
        "i_VI_iv_V",
        "i_III_VI_VII",
        "i_v_VI_VII",
        "i_VI_i_VII",
        "i_i_i_VII",
        "i_i_VII_VII",
        "i_VII_i_VII",
        "i_i_VI_VI",
        "i_VI_i_VI",
        "i_iv_i_iv",
    }
    for rec in RECIPES.values():
        assert len(rec["romans"]) == 4
    assert recipe_unique_count("pedal_i") == 1
    assert recipe_unique_count("i_i_VII_VII") == 2
    assert recipe_unique_count("i_VI_III_VII") == 4


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


def test_effective_chords_tiles_enabled():
    prog = realize("i_VII_i_VII", "F minor")
    prog["chords"][1]["enabled"] = False
    prog["chords"][3]["enabled"] = False
    eff = effective_chords(prog)
    assert [c["roman"] for c in eff] == ["i", "i", "i", "i"]
    four = realize("i_iv_VI_V", "F minor")
    four["chords"][3]["enabled"] = False
    assert [c["roman"] for c in effective_chords(four)] == ["i", "iv", "VI", "i"]
    four["chords"][2]["enabled"] = False
    assert [c["roman"] for c in effective_chords(four)] == ["i", "iv", "i", "iv"]


def test_edit_chords_set_roman_and_cannot_mute_last():
    prog = realize("i_VII_i_VII", "F minor")
    out = edit_chords(prog, "F minor", bar=1, roman="iv")
    assert out["chords"][1]["roman"] == "iv"
    assert out["recipe_id"] == "custom"
    muted = edit_chords(out, "F minor", bar=0, enabled=False)
    muted = edit_chords(muted, "F minor", bar=1, enabled=False)
    muted = edit_chords(muted, "F minor", bar=2, enabled=False)
    muted = edit_chords(muted, "F minor", bar=3, enabled=False)
    assert sum(1 for c in muted["chords"] if chord_enabled(c)) == 1


def test_set_chords_rewrites_bass_roots():
    prog = realize("pedal_i", "F minor")
    out = apply_edited_harmony(
        key="F minor",
        progression=prog,
        tracks=[{"id": "bass", "type": "bass", "octave": 2}],
        bar=2,
        roman="VII",
    )
    assert out["progression"]["chords"][2]["roman"] == "VII"
    bass = out["midi"]["bass"]
    notes = _lead_notes(bass, 2)
    bar2 = [n for n in notes if 8.0 <= n["start_beat"] < 12.0]
    assert bar2
    assert bar2[0]["midi"] % 12 == 3  # Eb


def test_pedal_i_same_root():
    prog = realize("pedal_i", "F minor")
    roots = [c["root_pc"] for c in prog["chords"]]
    assert len(set(roots)) == 1
    assert roots[0] == 5


def test_style_weights_prefer_prog_house():
    weights = _style_recipe_weights("prog house")
    two = {rid: weights[rid] for rid in RECIPES if is_two_cell_recipe(rid)}
    assert two["i_i_VI_VI"] == max(two.values())
    assert two["i_i_VI_VI"] >= two["pedal_i"]


def test_style_weights_techno_prefers_held():
    weights = _style_recipe_weights("techno")
    held = max(
        weights[rid]
        for rid in ("pedal_i", "i_i_i_VII", "i_i_VII_VII", "i_VII_i_VII")
    )
    assert held == max(weights.values())
    assert held > weights["i_VI_III_VII"]
    assert held > weights["i_III_VI_VII"]


def test_held_recipes_realize():
    prog = realize("i_i_VII_VII", "F minor")
    assert [c["roman"] for c in prog["chords"]] == ["i", "i", "VII", "VII"]
    assert [c["root_pc"] for c in prog["chords"]] == [5, 5, 3, 3]
    pedal = realize("i_i_i_VII", "F minor")
    assert [c["roman"] for c in pedal["chords"]] == ["i", "i", "i", "VII"]


def test_pick_recipe_avoids():
    for _ in range(40):
        rec = pick_recipe("prog house", avoid="i_iv_VI_V")
        assert rec["id"] != "i_iv_VI_V"
        assert rec["id"] in RECIPES


def test_pick_recipe_techno_usually_held():
    held = 0
    for _ in range(40):
        rec = pick_recipe("techno")
        n = recipe_unique_count(rec["id"])
        assert n <= 2
        if n <= 2:
            held += 1
    assert held == 40


def test_pick_recipe_only_two_cell():
    for style in ("", "techno", "prog house", "trance", "melodic techno"):
        for i in range(20):
            rec = pick_recipe(style, rng=__import__("random").Random(i))
            assert is_two_cell_recipe(rec["id"]), (style, rec["id"])


def test_pick_recipe_default_usually_held():
    held = 0
    for i in range(40):
        rec = pick_recipe("", rng=__import__("random").Random(i))
        if recipe_unique_count(rec["id"]) <= 2:
            held += 1
    assert held == 40


def test_bass_runner_repeats_root_sixteenths():
    prog = realize("pedal_i", "F minor")
    midi = dice_bass_grid(
        prog, octave=2, seed=4, density=0.7, variance=0.2, length=0.2, kind="runner"
    )
    assert midi["patternId"] == "prog-runner"
    notes = _lead_notes(midi, 2)
    assert len(notes) >= 8
    sixteenths = sum(1 for n in notes if abs(n["duration_beats"] - 0.25) < 0.05)
    assert sixteenths >= len(notes) * 0.6
    roots = sum(1 for n in notes if n["midi"] % 12 == 5)
    assert roots >= len(notes) * 0.55
    steps = [round(n["start_beat"] * 4) % 16 for n in notes]
    assert any(s % 2 == 1 for s in steps)


def test_dice_chords_writes_bass_runner():
    out = dice_chords(
        key="F minor",
        style="techno",
        tracks=[{"id": "bass", "type": "bass", "octave": 2}],
        seed=2,
        density=0.6,
    )
    bass = out["midi"]["bass"]
    assert str(bass["patternId"]).startswith("prog-")
    assert bass["patternId"] in {
        "prog-runner",
        "prog-bouncer",
        "prog-groove",
    }
    assert len(bass["grid"]) == 64
    assert sum(1 for c in bass["grid"] if c) >= 4


def test_bass_bouncer_hits_offbeats():
    prog = realize("pedal_i", "F minor")
    midi = dice_bass_grid(
        prog, octave=2, seed=1, density=0.5, variance=0.2, length=0.5, kind="bouncer"
    )
    assert midi["patternId"] == "prog-bouncer"
    hits0 = [s for s in range(16) if midi["grid"][s]]
    assert hits0
    assert any(s % 4 == 2 for s in hits0)


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
        midi = dice_lead_grid(
            prog, "F minor", seed=seed, octave=5, phrase="motif_echo"
        )
        notes = _lead_notes(midi, 5)
        assert notes
        for a, b in zip(notes, notes[1:]):
            assert abs(b["midi"] - a["midi"]) <= 7, (seed, a["midi"], b["midi"])


def test_dice_lead_avoid_moves_bar_start():
    prog = realize("i_VI_III_VII", "F minor")
    avoid = [5, 1, 8, 3]  # i–VI–III–VII roots
    midi = dice_lead_grid(prog, "F minor", seed=0, octave=5, avoid=avoid)
    notes = _lead_notes(midi, 5)
    assert notes
    assert notes[0]["midi"] % 12 != 5


def _is_downbeat(start_beat: float) -> bool:
    return abs(start_beat - round(start_beat)) < 1e-6


def test_dice_lead_downbeats_are_chord_tones():
    prog = realize("i_iv_VI_V", "F minor")
    for seed in range(20):
        midi = dice_lead_grid(prog, "F minor", seed=seed, octave=4)
        notes = _lead_notes(midi, 4)
        assert notes
        for n in notes:
            if not _is_downbeat(n["start_beat"]):
                continue
            bar = int(n["start_beat"] // 4)
            assert n["midi"] % 12 in prog["chords"][bar]["pcs"]


def test_dice_lead_passing_tones_are_aeolian():
    prog = realize("i_VI_III_VII", "F minor")
    key = prog["key"]
    passing = 0
    for seed in range(30):
        midi = dice_lead_grid(prog, "F minor", seed=seed, octave=4)
        for n in _lead_notes(midi, 4):
            if _is_downbeat(n["start_beat"]):
                continue
            bar = int(n["start_beat"] // 4)
            pc = n["midi"] % 12
            if pc in prog["chords"][bar]["pcs"]:
                continue
            passing += 1
            _deg, alter = pc_to_degree_alter(pc, key)
            assert alter == 0
    assert passing > 0


def test_dice_lead_per_track_octave():
    prog = realize("i_VI_III_VII", "C major")
    out = dice_lead(
        key="C major",
        progression=prog,
        tracks=[
            {"id": "lead", "type": "lead", "octave": 4},
            {"id": "lead2", "type": "arp", "octave": 5},
            {"id": "bass", "type": "bass", "octave": 2},
        ],
        seed=1,
    )
    assert "bass" not in out["midi"]
    assert "progression" not in out
    assert out["midi"]["lead"]["octave"] == 4
    assert out["midi"]["lead2"]["octave"] == 5
    n4 = _lead_notes(out["midi"]["lead"], 4)
    n5 = _lead_notes(out["midi"]["lead2"], 5)
    lo4 = degree_to_midi("C minor", 0, 4)
    lo5 = degree_to_midi("C minor", 0, 5)
    assert lo4 == 60 and lo5 == 72
    assert n4 and all(lo4 <= n["midi"] <= lo4 + 14 for n in n4)
    assert n5 and all(lo5 <= n["midi"] <= lo5 + 14 for n in n5)


def test_dice_lead_has_long_notes_and_rests():
    prog = realize("i_VI_III_VII", "F minor")
    midi = dice_lead_grid(prog, "F minor", seed=1, octave=4, phrase="hook_hold")
    assert midi["patternId"] == "prog-lead-hook_hold"
    lens = [int(c["length"]) for c in midi["grid"] if c]
    assert any(n >= 8 for n in lens)


def test_dice_lead_default_often_runner():
    prog = realize("pedal_i", "F minor")
    runners = 0
    for seed in range(30):
        midi = dice_lead_grid(prog, "F minor", seed=seed, octave=4)
        if str(midi["patternId"]).endswith("runner"):
            runners += 1
    assert runners >= 14


def test_dice_lead_motif_echo_repeats_hits():
    prog = realize("i_VI_III_VII", "F minor")
    midi = dice_lead_grid(prog, "F minor", seed=3, octave=4, phrase="motif_echo")
    assert midi["patternId"] == "prog-lead-motif_echo"
    hits0 = [s for s in range(16) if midi["grid"][s]]
    assert hits0
    for bar in range(1, 4):
        hits = [s for s in range(16) if midi["grid"][bar * 16 + s]]
        assert hits == hits0


def _lead_hit_count(midi: dict) -> int:
    return sum(1 for c in midi["grid"] if c)


def _bar_hits(midi: dict) -> list[list[int]]:
    return [
        [s for s in range(16) if midi["grid"][bar * 16 + s]] for bar in range(4)
    ]


def test_dice_lead_density_sparse_vs_dense():
    prog = realize("i_VI_III_VII", "F minor")
    sparse = []
    dense = []
    for seed in range(28):
        lo = dice_lead_grid(
            prog, "F minor", seed=seed, octave=4, density=0.0, variance=0.5, length=0.5
        )
        hi = dice_lead_grid(
            prog, "F minor", seed=seed, octave=4, density=1.0, variance=0.5, length=0.5
        )
        sparse.append(_lead_hit_count(lo))
        dense.append(_lead_hit_count(hi))
    assert sum(dense) > sum(sparse) * 1.25
    assert max(sparse) <= 28
    assert max(dense) >= 16


def test_motif_pools_include_sixteenths():
    def has16(pool):
        return any(any(s % 2 == 1 for s in motif) for motif in pool)

    assert has16(_MOTIF_RHYTHMS)
    assert has16(_MOTIF_RHYTHMS_DENSE)
    dense16 = sum(
        1 for m in _MOTIF_RHYTHMS_DENSE if any(s % 2 == 1 for s in m)
    )
    assert dense16 >= len(_MOTIF_RHYTHMS_DENSE) * 0.6


def test_dice_lead_dense_has_sixteenth_hits():
    prog = realize("i_VI_III_VII", "F minor")
    odd = 0
    total = 0
    for seed in range(24):
        midi = dice_lead_grid(
            prog, "F minor", seed=seed, octave=4, density=1.0, variance=0.5, length=0.2
        )
        for bar in range(4):
            for s in range(16):
                if not midi["grid"][bar * 16 + s]:
                    continue
                total += 1
                if s % 2 == 1:
                    odd += 1
    assert total
    assert odd >= 16
    assert odd / total >= 0.12


def test_dice_lead_length_short_vs_long():
    prog = realize("i_VI_III_VII", "F minor")
    short_avg = []
    long_avg = []
    for seed in range(24):
        lo = dice_lead_grid(
            prog, "F minor", seed=seed, octave=4, density=0.3, variance=0.5, length=0.0
        )
        hi = dice_lead_grid(
            prog, "F minor", seed=seed, octave=4, density=0.3, variance=0.5, length=1.0
        )
        notes_lo = _lead_notes(lo, 4)
        notes_hi = _lead_notes(hi, 4)
        assert notes_lo and notes_hi
        short_avg.append(
            sum(n["duration_beats"] for n in notes_lo) / len(notes_lo)
        )
        long_avg.append(
            sum(n["duration_beats"] for n in notes_hi) / len(notes_hi)
        )
    assert sum(long_avg) > sum(short_avg) * 1.4


def test_dice_lead_variance_repeat_vs_vary():
    prog = realize("i_VI_III_VII", "F minor")
    identical = 0
    different = 0
    for seed in range(40):
        midi = dice_lead_grid(
            prog, "F minor", seed=seed, octave=4, density=0.5, variance=0.0, length=0.5
        )
        hits = _bar_hits(midi)
        if hits[0] and all(h == hits[0] for h in hits[1:]):
            identical += 1
    for seed in range(40):
        midi = dice_lead_grid(
            prog, "F minor", seed=seed, octave=4, density=0.55, variance=1.0, length=0.5
        )
        hits = _bar_hits(midi)
        if hits[0] and any(h != hits[0] for h in hits[1:]):
            different += 1
    assert identical >= 18
    assert different >= 8


def test_dice_lead_shape_clamped():
    prog = realize("i_VI_III_VII", "F minor")
    midi = dice_lead_grid(
        prog,
        "F minor",
        seed=1,
        octave=4,
        density=9,
        variance=-3,
        length=None,
    )
    assert len(midi["grid"]) == 64
    assert any(c for c in midi["grid"])


def test_dice_lead_oct_only_when_not_track_octave():
    prog = realize("i_VI_III_VII", "C major")
    midi = dice_lead_grid(prog, "C major", seed=0, octave=4)
    assert any(c and c.get("oct") is None for c in midi["grid"])
    for cell in midi["grid"]:
        if not cell:
            continue
        if "oct" in cell:
            assert cell["oct"] != 4


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
    """Hear-it: #key = F major → bass midi.key is F minor; VI root is Db (49)."""
    prog = realize("i_VI_III_VII", "F major")
    bass = rewrite_bass_grid(prog, octave=2)
    assert bass["key"] == "F minor"
    assert prog["key"] == "F minor"
    notes = grid_to_notes(bass["grid"], key=bass["key"], octave=2, bars=4)
    vi_bars = [c["bar"] for c in prog["chords"] if c["roman"] == "VI"]
    assert vi_bars == [1]
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


def test_recipes_endpoint_lists_all():
    out = api_harmony_recipes()
    assert out["ok"] is True
    assert out["loop_bars"] == 4
    assert len(out["recipes"]) == len(RECIPES)
    ids = {r["id"] for r in out["recipes"]}
    assert "i_i_VII_VII" in ids
    assert "pedal_i" in ids


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


def test_dice_lead_no_progression_400():
    try:
        api_dice_lead(DiceLeadRequest(key="F minor", progression={}, tracks=[]))
        raise AssertionError("expected 400")
    except HTTPException as exc:
        assert exc.status_code == 400


def test_dice_lead_wrong_bars_400():
    try:
        api_dice_lead(
            DiceLeadRequest(
                key="F minor",
                progression={"recipe_id": "i_VI_III_VII", "bars": 8, "chords": []},
                tracks=[],
            )
        )
        raise AssertionError("expected 400")
    except HTTPException as exc:
        assert exc.status_code == 400


def test_dice_lead_no_lead_tracks_empty_midi():
    prog = realize("i_VI_III_VII", "F minor")
    out = dice_lead(
        key="F minor",
        progression=prog,
        tracks=[{"id": "bass", "type": "bass", "octave": 2}],
    )
    assert out["midi"] == {}
    assert "progression" not in out


def test_dice_lead_locked_theme_allowed():
    prog = realize("i_VI_III_VII", "F minor")
    prog["locked"] = True
    out = api_dice_lead(
        DiceLeadRequest(
            key="F minor",
            progression=prog,
            tracks=[
                {
                    "id": "lead",
                    "type": "lead",
                    "octave": 4,
                    "midi": {
                        "source": "user",
                        "key": "F minor",
                        "bars": 1,
                        "grid": [None] * 16,
                    },
                }
            ],
            seed=0,
        )
    )
    assert out["ok"] is True
    lead = out["midi"]["lead"]
    assert str(lead["patternId"]).startswith("prog-lead")
    assert lead["source"] == "progression"
    assert lead["bars"] == 4
    assert lead["octave"] == 4
    assert lead["key"] == "F minor"
    assert len(lead["grid"]) == 64
