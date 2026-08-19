"""Save/load/export of session progression (PR 5)."""

from __future__ import annotations

from pathlib import Path

import mido
from fastapi import HTTPException

from backend import app as backend_app
from backend.app import (
    ApplyHarmonyRequest,
    SaveLoopRequest,
    api_harmony_apply,
    get_loop,
    save_loop,
)
from backend.export_loop import export_loop
from backend.harmony import dice_chords, dice_lead_grid, realize, rewrite_bass_grid


def _saves(tmp_path: Path, monkeypatch) -> Path:
    dest = tmp_path / "saves"
    dest.mkdir()
    monkeypatch.setattr(backend_app, "SAVES_DIR", dest)
    return dest


def _lead_slot(midi: dict) -> dict:
    return {
        "type": "lead",
        "name": "Serum lead",
        "kind": "serum",
        "empty": False,
        "midi": midi,
    }


def test_two_saves_without_id_are_separate(tmp_path: Path, monkeypatch):
    dest = _saves(tmp_path, monkeypatch)
    first = save_loop(
        SaveLoopRequest(
            name="Take A",
            key="F minor",
            track_order=["kick"],
            slots={"kick": {"type": "kick"}},
        )
    )
    second = save_loop(
        SaveLoopRequest(
            name="Take B",
            key="F minor",
            track_order=["kick"],
            slots={"kick": {"type": "kick"}},
        )
    )
    assert first["id"] != second["id"]
    files = sorted(p.name for p in dest.glob("*.json"))
    assert len(files) == 2
    assert get_loop(first["id"])["name"] == "Take A"
    assert get_loop(second["id"])["name"] == "Take B"
    same_a = save_loop(
        SaveLoopRequest(
            name="Take A",
            key="F minor",
            track_order=["kick"],
            slots={"kick": {"type": "kick"}},
        )
    )
    assert same_a["id"] != first["id"]
    assert get_loop(first["id"])["name"] == "Take A"
    assert len(list(dest.glob("*.json"))) == 3


def test_new_save_omits_progression_when_missing(tmp_path: Path, monkeypatch):
    _saves(tmp_path, monkeypatch)
    out = save_loop(
        SaveLoopRequest(
            name="Plain",
            key="F minor",
            track_order=["kick"],
            slots={"kick": {"type": "kick"}},
        )
    )
    assert out["has_progression"] is False
    doc = get_loop(out["id"])
    assert "progression" not in doc


def test_save_load_roundtrip_theme_and_64_step(tmp_path: Path, monkeypatch):
    _saves(tmp_path, monkeypatch)
    prog = realize("i_VI_III_VII", "F minor")
    lead = dice_lead_grid(prog, "F minor", seed=1, octave=4)
    bass = rewrite_bass_grid(prog, octave=2)
    out = save_loop(
        SaveLoopRequest(
            name="Theme",
            key="F minor",
            style="Melodic Techno",
            track_order=["bass", "lead"],
            slots={
                "bass": {"type": "bass", "kind": "serum", "midi": bass},
                "lead": _lead_slot(lead),
            },
            progression=prog,
        )
    )
    assert out["ok"] is True
    assert out["has_progression"] is True
    doc = get_loop(out["id"])
    assert doc["progression"]["recipe_id"] == "i_VI_III_VII"
    assert doc["progression"]["bars"] == 4
    assert doc["progression"]["key"] == "F minor"
    loaded_lead = doc["slots"]["lead"]["midi"]
    assert loaded_lead["source"] == "progression"
    assert loaded_lead["bars"] == 4
    assert len(loaded_lead["grid"]) == 64
    loaded_bass = doc["slots"]["bass"]["midi"]
    assert loaded_bass["source"] == "progression"
    assert loaded_bass["bars"] == 4
    assert len(loaded_bass["grid"]) == 64


def test_overwrite_none_keeps_previous_then_reconciles(tmp_path: Path, monkeypatch):
    _saves(tmp_path, monkeypatch)
    prog = realize("i_VI_III_VII", "F minor")
    first = save_loop(
        SaveLoopRequest(
            name="Keep",
            key="F minor",
            track_order=["bass"],
            slots={"bass": {"type": "bass"}},
            progression=prog,
        )
    )
    second = save_loop(
        SaveLoopRequest(
            name="Keep",
            id=first["id"],
            key="C major",
            track_order=["bass"],
            slots={"bass": {"type": "bass"}},
            progression=None,
        )
    )
    assert second["has_progression"] is True
    doc = get_loop(first["id"])
    assert doc["progression"]["recipe_id"] == "i_VI_III_VII"
    assert doc["progression"]["key"] == "C minor"
    assert [c["root_pc"] for c in doc["progression"]["chords"]] == [0, 8, 3, 10]


def test_overwrite_dict_replaces_theme(tmp_path: Path, monkeypatch):
    _saves(tmp_path, monkeypatch)
    first = save_loop(
        SaveLoopRequest(
            name="Swap",
            key="F minor",
            track_order=["bass"],
            slots={"bass": {"type": "bass"}},
            progression=realize("i_VI_III_VII", "F minor"),
        )
    )
    save_loop(
        SaveLoopRequest(
            name="Swap",
            id=first["id"],
            key="F minor",
            track_order=["bass"],
            slots={"bass": {"type": "bass"}},
            progression=realize("i_VII_VI_VII", "F minor"),
        )
    )
    doc = get_loop(first["id"])
    assert doc["progression"]["recipe_id"] == "i_VII_VI_VII"


def test_invalid_bars_rejected(tmp_path: Path, monkeypatch):
    _saves(tmp_path, monkeypatch)
    try:
        save_loop(
            SaveLoopRequest(
                name="Bad",
                track_order=["bass"],
                slots={"bass": {"type": "bass"}},
                progression={"recipe_id": "i_VI_III_VII", "bars": 8, "chords": []},
            )
        )
        raise AssertionError("expected 400")
    except HTTPException as exc:
        assert exc.status_code == 400


def test_lead_source_survives_then_apply_rewrites(tmp_path: Path, monkeypatch):
    _saves(tmp_path, monkeypatch)
    prog = realize("i_VI_III_VII", "F minor")
    lead = dice_lead_grid(prog, "F minor", seed=2, octave=4)
    assert lead["source"] == "progression"
    assert lead["bars"] == 4
    saved = save_loop(
        SaveLoopRequest(
            name="Lead persist",
            key="F minor",
            track_order=["lead"],
            slots={"lead": _lead_slot(lead)},
            progression=prog,
        )
    )
    doc = get_loop(saved["id"])
    loaded = doc["slots"]["lead"]["midi"]
    assert loaded["source"] == "progression"
    assert loaded["bars"] == 4
    assert len(loaded["grid"]) == 64
    applied = api_harmony_apply(
        ApplyHarmonyRequest(
            key="C major",
            progression=doc["progression"],
            tracks=[
                {
                    "id": "lead",
                    "type": "lead",
                    "octave": 4,
                    "midi": loaded,
                }
            ],
        )
    )
    assert "lead" in applied["midi"]
    assert applied["midi"]["lead"]["source"] == "progression"
    assert applied["midi"]["lead"]["key"] == "C minor"
    assert applied["progression"]["key"] == "C minor"


def test_export_after_dice_bass_mid_not_drone(tmp_path: Path):
    diced = dice_chords(
        key="F minor",
        style="melodic techno",
        tracks=[{"id": "bass", "type": "bass", "octave": 2}],
        avoid_recipe_id="pedal_i",
    )
    bass = diced["midi"]["bass"]

    wav = tmp_path / "bounce.wav"
    wav.write_bytes(b"RIFF" + b"\x00" * 64)
    fxp = tmp_path / "preset.fxp"
    fxp.write_bytes(b"fxp")

    def fake_render(payload):
        assert payload.get("grid") is not None
        assert len(payload["grid"]) == 64
        return {"ok": True, "wav": str(wav)}

    out = export_loop(
        export_root=tmp_path / "exports",
        bpm=140,
        key="F minor",
        style="Melodic Techno",
        bars=4,
        name="After Dice",
        tracks=[
            {
                "id": "bass",
                "type": "bass",
                "path": str(fxp),
                "name": "Serum bass",
                "kind": "serum",
                "midi": bass,
            }
        ],
        render_serum=fake_render,
        sync_user_library=False,
        sync_ableton_drop=False,
        write_als=False,
    )
    mid = next(f for f in out["files"] if f.get("role") == "midi")
    pcs: set[int] = set()
    for tr in mido.MidiFile(mid["abs_path"]).tracks:
        for msg in tr:
            if msg.type == "note_on" and msg.velocity > 0:
                pcs.add(msg.note % 12)
    assert len(pcs) > 1
