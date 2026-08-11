"""Ableton Live Set (.als) project writer."""

from __future__ import annotations

import gzip
import struct
import wave
from pathlib import Path
import xml.etree.ElementTree as ET

from backend.export_als import TEMPLATE_PATH, write_als_project
from backend.export_loop import export_loop


def _tiny_wav(path: Path, ms: int = 50) -> None:
    sr = 44100
    n = max(1, int(sr * ms / 1000))
    frames = b"".join(
        struct.pack("<h", 8000 if i % 16 < 8 else -8000) for i in range(n)
    )
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(frames)


def test_template_exists():
    assert TEMPLATE_PATH.is_file(), f"missing template: {TEMPLATE_PATH}"


def test_write_als_project(tmp_path: Path):
    a = tmp_path / "01_kick.wav"
    b = tmp_path / "02_bass.wav"
    _tiny_wav(a, 40)
    _tiny_wav(b, 40)

    out = write_als_project(
        parent_dir=tmp_path / "out",
        project_name="Unit Test Loop",
        bpm=140,
        bars=4,
        audio_files=[
            {"name": "01_kick.wav", "abs_path": a, "track": "kick"},
            {"name": "02_bass.wav", "abs_path": b, "track": "bass"},
        ],
    )
    assert out["ok"], out
    als = Path(out["als_path"])
    proj = Path(out["project_dir"])
    assert als.is_file()
    assert als.suffix.lower() == ".als"
    # Default: .als sits in parent_dir (export folder), not a nested Project/
    assert als.parent.resolve() == (tmp_path / "out").resolve()
    assert (proj / "Ableton Project Info").is_dir()
    assert (proj / "Samples" / "Imported" / "01_kick.wav").is_file()
    assert (proj / "Samples" / "Imported" / "02_bass.wav").is_file()
    assert (proj / "OPEN_THIS_IN_ABLETON.txt").is_file()

    # Gzip XML with two audio tracks + tempo
    xml = gzip.decompress(als.read_bytes()).decode("utf-8")
    root = ET.fromstring(xml)
    assert root.tag == "Ableton"
    tracks = list(root.find("LiveSet").find("Tracks").findall("AudioTrack"))
    assert len(tracks) == 2
    assert "Samples/Imported/01_kick.wav" in xml
    assert 'Manual Value="140' in xml or 'Manual Value="140.0"' in xml
    # Live rejects these as "unknown class …" / corrupt
    assert "MidiEditorLaneModel" not in xml
    assert "ExpressionLanes" not in xml
    assert "ContentLanes" not in xml
    assert "AudioOut/Main" not in xml
    # NextPointeeId must exceed every Id= in the document
    max_id = 0
    for el in root.iter():
        if "Id" in el.attrib:
            try:
                max_id = max(max_id, int(el.attrib["Id"]))
            except ValueError:
                pass
    npi = root.find("LiveSet").find("NextPointeeId")
    assert npi is not None
    assert int(npi.get("Value")) > max_id
    assert int(npi.get("Value")) >= 100_000
    assert out.get("next_pointee_id", 0) > max_id
    # Stem sets: no returns, no send knobs (Live is strict about matching counts)
    tracks_el = root.find("LiveSet").find("Tracks")
    assert sum(1 for t in tracks_el if t.tag == "ReturnTrack") == 0
    assert sum(1 for _ in root.iter("TrackSendHolder")) == 0
    for sp in root.iter("SendsPre"):
        assert len(list(sp)) == 0
    # Scene count == session slot count on every track sequencer
    n_scenes = len(list(root.find("LiveSet").find("Scenes")))
    assert n_scenes >= 1
    for track in tracks_el:
        if track.tag != "AudioTrack":
            continue
        for seq_name in ("MainSequencer", "FreezeSequencer"):
            for seq in track.iter(seq_name):
                csl = seq.find("ClipSlotList")
                if csl is None:
                    continue
                n_slots = sum(1 for s in csl if s.tag == "ClipSlot")
                assert n_slots == n_scenes, f"{seq_name} slots={n_slots} scenes={n_scenes}"
        # Arrangement: one AudioClip in Sample/ArrangerAutomation/Events
        ms = track.find("DeviceChain/MainSequencer")
        if ms is None:
            ms = next(track.iter("MainSequencer"), None)
        assert ms is not None
        events = ms.find("Sample/ArrangerAutomation/Events")
        assert events is not None
        arr_clips = [c for c in events if c.tag == "AudioClip"]
        assert len(arr_clips) == 1, "expected arrangement clip"
        assert arr_clips[0].get("Time") == "0"
        assert float(arr_clips[0].find("CurrentEnd").get("Value")) == 16.0  # 4 bars
    # Transport loop brace covers the same 4 bars
    transport = root.find("LiveSet").find("Transport")
    assert transport is not None
    assert transport.find("LoopOn").get("Value") == "true"
    assert float(transport.find("LoopStart").get("Value")) == 0.0
    assert float(transport.find("LoopLength").get("Value")) == 16.0


def test_export_loop_writes_als(tmp_path: Path):
    sample = tmp_path / "kick.wav"
    _tiny_wav(sample, 30)

    out = export_loop(
        export_root=tmp_path / "exports",
        bpm=128,
        key="A minor",
        style="Techno",
        bars=4,
        name="Als Export Test",
        tracks=[
            {
                "id": "kick",
                "type": "kick",
                "path": str(sample),
                "name": "kick.wav",
                "kind": "sample",
            }
        ],
        render_serum=None,
        sync_user_library=False,
        write_als=True,
    )
    assert out.get("als_path")
    assert Path(out["als_path"]).is_file()
    assert out.get("als", {}).get("ok")
    # .als is in the same folder as the stems
    assert Path(out["als_path"]).parent == Path(out["folder"])
    assert any(f.get("kind") == "als" for f in out["files"])


def test_export_loop_skip_als(tmp_path: Path):
    sample = tmp_path / "kick.wav"
    _tiny_wav(sample, 30)

    out = export_loop(
        export_root=tmp_path / "exports",
        bpm=128,
        key="A minor",
        style="Techno",
        bars=4,
        tracks=[
            {
                "id": "kick",
                "type": "kick",
                "path": str(sample),
                "name": "kick.wav",
                "kind": "sample",
            }
        ],
        render_serum=None,
        sync_user_library=False,
        write_als=False,
    )
    assert out.get("als_path") is None
    assert out.get("als") is None
