"""Full-loop sample stem offline render."""

from __future__ import annotations

import struct
import wave
from pathlib import Path

from backend.render_sample_loop import render_sample_loop
from backend.timing import cycle_sec


def _write_short_wav(path: Path, *, sr: int = 44100, ms: int = 40) -> None:
    n = max(1, int(sr * ms / 1000))
    # simple click
    frames = bytearray()
    for i in range(n):
        # decay square-ish blip
        amp = int(12000 * (1.0 - i / n))
        frames += struct.pack("<h", amp if (i // 8) % 2 == 0 else -amp)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(frames))


def test_kick_loop_longer_than_oneshot(tmp_path: Path):
    src = tmp_path / "kick.wav"
    _write_short_wav(src, ms=30)
    dest = tmp_path / "kick_loop.wav"
    bpm = 140
    bars = 4
    out = render_sample_loop(src, dest, track_type="kick", bpm=bpm, bars=bars)
    assert out["ok"], out
    assert dest.is_file()
    # Full loop duration ≈ cycle_sec
    expected = cycle_sec(bpm, bars)
    assert abs(out["duration_sec"] - expected) < 0.05
    # File should be much larger than 30ms one-shot
    assert dest.stat().st_size > 50_000
    assert out["mode"] == "pattern"


def test_export_uses_loop_render(tmp_path: Path):
    from backend.export_loop import export_loop

    src = tmp_path / "my_kick.wav"
    _write_short_wav(src, ms=25)
    result = export_loop(
        export_root=tmp_path / "exports",
        bpm=140,
        key="F minor",
        style="Techno",
        bars=4,
        tracks=[
            {
                "id": "kick",
                "type": "kick",
                "path": str(src),
                "name": "my_kick.wav",
                "kind": "sample",
            }
        ],
        render_serum=None,
        sync_user_library=False,
    )
    audio = [f for f in result["files"] if f.get("role") == "audio"]
    assert len(audio) == 1
    assert audio[0]["kind"] == "sample_loop"
    p = Path(audio[0]["abs_path"])
    assert p.is_file()
    # ~4 bars @ 140bpm stereo/mono 16-bit is hundreds of KB
    assert p.stat().st_size > 100_000
