"""Loop export folder layout (no Serum host)."""

from __future__ import annotations

from pathlib import Path

from backend.export_loop import export_loop


def _tiny_wav(path: Path, ms: int = 30) -> None:
    import struct
    import wave

    sr = 44100
    n = max(1, int(sr * ms / 1000))
    frames = b"".join(struct.pack("<h", 8000 if i % 16 < 8 else -8000) for i in range(n))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(frames)


def test_export_sample_and_midi_flat(tmp_path: Path):
    sample = tmp_path / "kick.wav"
    _tiny_wav(sample, ms=30)

    grid = [None] * 16
    grid[0] = {"degree": 0, "length": 4, "vel": 100}
    grid[8] = {"degree": 2, "length": 2, "vel": 90}

    out = export_loop(
        export_root=tmp_path / "exports",
        bpm=140,
        key="F minor",
        style="Techno",
        bars=4,
        name="Unit Test Loop",
        tracks=[
            {
                "id": "kick",
                "type": "kick",
                "path": str(sample),
                "name": "kick.wav",
                "kind": "sample",
            },
            {
                "id": "bass",
                "type": "bass",
                "path": None,
                "name": "Serum bass",
                "kind": "serum",
                "midi": {"grid": grid, "octave": 2, "key": "F minor"},
            },
        ],
        render_serum=None,
        sync_user_library=False,
    )
    folder = Path(out["folder"])
    assert folder.is_dir()
    assert (folder / "manifest.json").is_file()
    # Flat: files live in folder root (not audio/midi subdirs)
    assert len(out["files"]) >= 2
    for f in out["files"]:
        assert (folder / f["name"]).is_file()
        assert "audio/" not in f["file"] and "midi/" not in f.get("file", "")
    # Sample/preset-based names (not generic Kick/Bass role labels)
    wavs = [f["name"] for f in out["files"] if f["name"].endswith(".wav")]
    assert any("kick" in n.lower() for n in wavs), wavs
    mids = [f["name"] for f in out["files"] if f["name"].endswith(".mid")]
    assert any("midi" in n.lower() for n in mids), mids
    # Kick is full-loop stem, not raw one-shot copy
    kick_audio = next(f for f in out["files"] if f.get("role") == "audio")
    assert kick_audio["kind"] == "sample_loop"
    assert Path(kick_audio["abs_path"]).stat().st_size > 100_000
    # ABLETON_DROP mirror
    drop = tmp_path / "exports" / "ABLETON_DROP"
    assert drop.is_dir()
    assert any(drop.glob("*.wav")) or any(drop.glob("*.mid"))


def test_export_serum_via_fake_render(tmp_path: Path):
    wav = tmp_path / "bounce.wav"
    wav.write_bytes(b"RIFF" + b"\x00" * 64)

    def fake_render(payload):
        assert payload.get("fxp")
        assert payload.get("grid") is not None
        return {"ok": True, "wav": str(wav)}

    grid = [{"degree": 0, "length": 16, "vel": 100}] + [None] * 15
    fxp = tmp_path / "preset.fxp"
    fxp.write_bytes(b"fxp")

    out = export_loop(
        export_root=tmp_path / "exports",
        bpm=140,
        key="C minor",
        style="Techno",
        bars=4,
        tracks=[
            {
                "id": "bass",
                "type": "bass",
                "path": str(fxp),
                "name": "Deep Bass",
                "kind": "serum",
                "midi": {"grid": grid, "octave": 2, "key": "C minor"},
            }
        ],
        render_serum=fake_render,
        sync_user_library=False,
    )
    assert any(f["kind"] == "serum" for f in out["files"])
    assert any(f["role"] == "midi" for f in out["files"])
    assert Path(out["files"][0]["abs_path"]).is_file()
