"""Write an Ableton Live Set project folder (.als + Samples) from exported stems.

.als files are gzip-compressed XML. We clone a sanitized single-track template
(backend/templates/live_set_template.xml) per audio stem so Live can open a
real project instead of only drag-and-drop clips.
"""

from __future__ import annotations

import gzip
import re
import shutil
import wave
from copy import deepcopy
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "live_set_template.xml"

# RelativePathType: 3 = relative to the Live Set's project folder
_PROJECT_RELATIVE = "3"

# Live 12-only / rejected nodes that trigger "unknown class …" corrupt errors
_DROP_TAGS = frozenset(
    {
        "ExpressionLanes",
        "ContentLanes",
        "MidiEditorLaneModel",
        "InstrumentMeld",
        "Roar",
        "MxPatchRef",
        "DetailClipKeyMidis",
    }
)


def _strip_unknown_live_nodes(root: ET.Element) -> None:
    """Remove schema nodes older Live rejects as 'unknown class'."""
    changed = True
    while changed:
        changed = False
        for parent in list(root.iter()):
            for child in list(parent):
                if child.tag in _DROP_TAGS:
                    parent.remove(child)
                    changed = True


def _load_template(path: Path) -> ET.Element:
    raw = path.read_text(encoding="utf-8")
    # Live 12 Master bus rename — Live 11 needs Master
    raw = raw.replace("AudioOut/Main", "AudioOut/Master")
    root = ET.fromstring(raw)
    _strip_unknown_live_nodes(root)
    # Compatible header (Live 12 still opens Live 11 sets)
    root.set("MajorVersion", "5")
    root.set("MinorVersion", "11.0_11300")
    root.set("SchemaChangeCount", "3")
    root.set("Creator", "Ableton Live 11.3.21")
    root.set("Revision", "reroll-als-export")
    return root


def _slug_project(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (name or "").strip(), flags=re.UNICODE)
    s = re.sub(r"[-\s]+", " ", s).strip()
    return (s[:48] if s else "Reroll Loop")


def _wav_frames_and_rate(path: Path) -> tuple[int, int]:
    """Return (nframes, framerate) for a WAV; fallback 1s @ 44.1k."""
    try:
        with wave.open(str(path), "rb") as wf:
            return int(wf.getnframes()), int(wf.getframerate() or 44100)
    except Exception:
        try:
            size = path.stat().st_size
            # rough PCM16 mono estimate after 44-byte header
            frames = max(1, (size - 44) // 2)
            return frames, 44100
        except OSError:
            return 44100, 44100


def _set_value(parent: ET.Element | None, tag: str, value: str) -> None:
    if parent is None:
        return
    el = parent.find(tag)
    if el is not None:
        el.set("Value", value)


def _set_all(root: ET.Element, tag: str, value: str) -> None:
    for el in root.iter(tag):
        if "Value" in el.attrib:
            el.set("Value", value)


def _renumber_ids(track: ET.Element, base_id: int) -> int:
    """Assign unique Id attributes under a track subtree. Returns next free id."""
    n = base_id
    for el in track.iter():
        if "Id" in el.attrib:
            el.set("Id", str(n))
            n += 1
    return n


def _max_id_in_tree(root: ET.Element) -> int:
    """Highest numeric Id= attribute anywhere in the document."""
    m = 0
    for el in root.iter():
        raw = el.attrib.get("Id")
        if raw is None:
            continue
        try:
            m = max(m, int(raw))
        except (TypeError, ValueError):
            continue
    return m


def _strip_returns_and_sends(root: ET.Element) -> dict[str, int]:
    """
    Stem exports don't need reverb returns. Live is strict:

      send knobs on every track  ==  number of ReturnTracks
      SendsPre / SendPreBool count must match too

    Easiest valid layout: **zero returns and zero sends**.
    """
    returns_removed = 0
    send_holders_removed = 0
    send_pre_removed = 0

    # Multiple passes — nested remove while iterating can skip siblings
    for _ in range(8):
        changed = False
        ls = root.find("LiveSet")
        tracks_el = ls.find("Tracks") if ls is not None else None
        if tracks_el is not None:
            for t in list(tracks_el):
                if t.tag == "ReturnTrack":
                    tracks_el.remove(t)
                    returns_removed += 1
                    changed = True
        for parent in list(root.iter()):
            if parent.tag == "Sends":
                for child in list(parent):
                    if child.tag == "TrackSendHolder":
                        parent.remove(child)
                        send_holders_removed += 1
                        changed = True
            if parent.tag == "SendsPre":
                for child in list(parent):
                    parent.remove(child)
                    send_pre_removed += 1
                    changed = True
        if not changed:
            break

    return {
        "returns_removed": returns_removed,
        "send_holders_removed": send_holders_removed,
        "send_pre_removed": send_pre_removed,
    }


def _strip_sends_from_element(el: ET.Element) -> int:
    """Remove TrackSendHolder nodes under an element (e.g. prototype track)."""
    n = 0
    for parent in list(el.iter()):
        if parent.tag != "Sends":
            continue
        for child in list(parent):
            if child.tag == "TrackSendHolder":
                parent.remove(child)
                n += 1
    return n


def _xml_force_strip_returns_sends(xml_text: str) -> tuple[str, dict[str, int]]:
    """Last-resort string scrub so a stale worker can't ship bad send counts."""
    counts = {"ReturnTrack": 0, "TrackSendHolder": 0, "SendPreBool": 0}
    # Outer return tracks first (contain nested sends)
    for tag in ("ReturnTrack", "TrackSendHolder", "SendPreBool"):
        pat = re.compile(rf"<{tag}\b[^>]*/>|<{tag}\b[^>]*>.*?</{tag}>", re.DOTALL)

        def _sub(m: re.Match[str], t: str = tag) -> str:
            counts[t] += 1
            return ""

        xml_text, _ = pat.subn(_sub, xml_text)
    return xml_text, counts


def _assert_clean_sends(root: ET.Element) -> None:
    n_ret = sum(1 for _ in root.iter("ReturnTrack"))
    n_hold = sum(1 for _ in root.iter("TrackSendHolder"))
    n_pre = sum(1 for _ in root.iter("SendPreBool"))
    if n_ret or n_hold or n_pre:
        raise RuntimeError(
            f"ALS still dirty after strip: ReturnTrack={n_ret} "
            f"TrackSendHolder={n_hold} SendPreBool={n_pre}"
        )


def _sync_sends_to_returns(root: ET.Element) -> dict[str, int]:
    """Back-compat name — now strips returns+sends for a valid stem set."""
    return _strip_returns_and_sends(root)


def _slot_has_clip(slot: ET.Element) -> bool:
    return any(True for _ in slot.iter("AudioClip")) or any(
        True for _ in slot.iter("MidiClip")
    )


def _make_empty_clip_slot(slot_id: int = 0) -> ET.Element:
    slot = ET.Element("ClipSlot", Id=str(slot_id))
    ET.SubElement(slot, "LomId", Value="0")
    inner = ET.SubElement(slot, "ClipSlot")
    ET.SubElement(inner, "Value")
    ET.SubElement(slot, "HasStop", Value="true")
    ET.SubElement(slot, "NeedRefreeze", Value="true")
    return slot


def _normalize_session_slots(root: ET.Element, n_slots: int = 1) -> dict[str, int]:
    """
    Live requires EVERY ClipSlotList length == Scenes count
    (MainSequencer, FreezeSequencer, AudioSequencer, MainTrack, …).

    Template often has Main=4, Freeze=53, Scenes=8 → \"slot count mismatch\".
    Collapse everything to one scene / one slot (clip in MainSequencer only).
    """
    n_slots = max(1, min(16, int(n_slots)))
    ls = root.find("LiveSet")
    if ls is None:
        return {"scenes": 0, "lists": 0}

    # --- Scenes ---
    scenes_el = ls.find("Scenes")
    if scenes_el is not None:
        existing = list(scenes_el)
        scene_proto = deepcopy(existing[0]) if existing else None
        for s in existing:
            scenes_el.remove(s)
        if scene_proto is not None:
            for i in range(n_slots):
                sc = deepcopy(scene_proto)
                name_el = sc.find("Name")
                if name_el is not None:
                    name_el.set("Value", "Reroll" if i == 0 else "")
                scenes_el.append(sc)

    # Blank slot prototype from any empty ClipSlot in the doc
    empty_proto: ET.Element | None = None
    for csl in root.iter("ClipSlotList"):
        for slot in csl:
            if slot.tag == "ClipSlot" and not _slot_has_clip(slot):
                empty_proto = deepcopy(slot)
                break
        if empty_proto is not None:
            break

    # Parent map so we know if a ClipSlotList sits under MainSequencer
    parent_of: dict[ET.Element, ET.Element] = {}
    for parent in root.iter():
        for child in parent:
            parent_of[child] = parent

    lists_fixed = 0
    # Snapshot list first — tree mutates as we rewrite children
    all_csl = list(root.iter("ClipSlotList"))
    for csl in all_csl:
        parent = parent_of.get(csl)
        parent_tag = parent.tag if parent is not None else ""
        slots = [s for s in list(csl) if s.tag == "ClipSlot"]
        filled = [s for s in slots if _slot_has_clip(s)]
        blanks = [s for s in slots if not _slot_has_clip(s)]
        blank = (
            deepcopy(blanks[0])
            if blanks
            else (deepcopy(empty_proto) if empty_proto is not None else None)
        )

        for s in list(csl):
            csl.remove(s)

        keep_clip = parent_tag == "MainSequencer" and bool(filled)
        for i in range(n_slots):
            if keep_clip and i == 0:
                slot = deepcopy(filled[0])
            elif blank is not None:
                slot = deepcopy(blank)
            else:
                slot = _make_empty_clip_slot(i)
            slot.set("Id", str(i))
            csl.append(slot)
        lists_fixed += 1

    return {"scenes": n_slots, "lists": lists_fixed}


def _assert_slot_counts(root: ET.Element) -> None:
    ls = root.find("LiveSet")
    if ls is None:
        return
    scenes_el = ls.find("Scenes")
    n_scenes = len(list(scenes_el)) if scenes_el is not None else 0
    bad: list[str] = []
    for csl in root.iter("ClipSlotList"):
        n = sum(1 for s in csl if s.tag == "ClipSlot")
        if n != n_scenes:
            bad.append(f"ClipSlotList slots={n} scenes={n_scenes}")
    if bad:
        raise RuntimeError("ALS slot count mismatch: " + "; ".join(bad[:6]))


def _configure_audio_track(
    track: ET.Element,
    *,
    track_id: int,
    name: str,
    rel_sample: str,
    abs_sample: Path,
    beat_length: float,
    color: int,
) -> int:
    """Mutate a cloned AudioTrack for one stem. Returns next free Id."""
    track.set("Id", str(track_id))
    frames, rate = _wav_frames_and_rate(abs_sample)
    size = 0
    try:
        size = abs_sample.stat().st_size
    except OSError:
        pass

    # Track name
    name_el = track.find("Name")
    if name_el is not None:
        _set_value(name_el, "EffectiveName", name)
        _set_value(name_el, "UserName", name)
        _set_value(name_el, "MemorizedFirstClipName", name)

    color_el = track.find("Color")
    if color_el is not None:
        color_el.set("Value", str(color % 70))

    # Sample path refs
    for el in track.iter("RelativePath"):
        el.set("Value", rel_sample.replace("\\", "/"))
    for el in track.iter("RelativePathType"):
        el.set("Value", _PROJECT_RELATIVE)
    for el in track.iter("Path"):
        # Absolute path helps Live locate if relative fails
        el.set("Value", str(abs_sample.resolve()))
    for el in track.iter("OriginalFileSize"):
        el.set("Value", str(size))
    for el in track.iter("DefaultDuration"):
        el.set("Value", str(frames))
    for el in track.iter("DefaultSampleRate"):
        el.set("Value", str(rate))
    for el in track.iter("LivePackName"):
        el.set("Value", "")
    for el in track.iter("LivePackId"):
        el.set("Value", "")
    for el in track.iter("BrowserContentPath"):
        el.set("Value", "")

    beat_s = str(float(beat_length))
    for clip in track.iter("AudioClip"):
        _set_value(clip, "Name", name)
        _set_value(clip, "CurrentStart", "0")
        _set_value(clip, "CurrentEnd", beat_s)
        _set_value(clip, "IsWarped", "true")
        loop = clip.find("Loop")
        if loop is not None:
            _set_value(loop, "LoopOn", "true")
            _set_value(loop, "LoopStart", "0")
            _set_value(loop, "LoopEnd", beat_s)
            _set_value(loop, "StartRelative", "0")
            _set_value(loop, "OutMarker", beat_s)
            # Hidden loop bounds if present
            for tag in ("HiddenLoopStart", "HiddenLoopEnd"):
                h = loop.find(tag)
                if h is not None and "Value" in h.attrib:
                    h.set("Value", "0" if "Start" in tag else beat_s)

    # Unique Ids for nested elements (avoid Live collisions across tracks)
    return _renumber_ids(track, track_id * 1000 + 1)


def write_als_project(
    *,
    parent_dir: Path,
    project_name: str,
    bpm: float,
    bars: int,
    audio_files: list[dict[str, Any]],
    template_path: Path | None = None,
    nest_project_folder: bool = False,
) -> dict[str, Any]:
    """
    Write a Live Set into ``parent_dir`` (default) so the ``.als`` sits next to
    exported stems and is obvious in Explorer.

    With ``nest_project_folder=True``, creates ``{name} Project/`` instead
    (classic Ableton layout).

    ``audio_files`` items: ``{"name": stem_filename, "abs_path": Path|str, "track": display}``
    """
    tpl = Path(template_path or TEMPLATE_PATH)
    if not tpl.is_file():
        return {
            "ok": False,
            "error": f"ALS template missing: {tpl}",
        }

    display = _slug_project(project_name)
    parent = Path(parent_dir)
    parent.mkdir(parents=True, exist_ok=True)
    # Default: .als lives in the export folder itself (visible next to .wav)
    project_dir = parent / f"{display} Project" if nest_project_folder else parent
    samples_dir = project_dir / "Samples" / "Imported"
    info_dir = project_dir / "Ableton Project Info"
    samples_dir.mkdir(parents=True, exist_ok=True)
    info_dir.mkdir(parents=True, exist_ok=True)
    # Marker file so Live treats the folder as a Project
    (info_dir / "Project.cfg").write_text(
        "\n".join(
            [
                "[Ableton Project]",
                "Creator=Reroll",
                f"Name={display}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    try:
        root = _load_template(tpl)
    except ET.ParseError as exc:
        return {"ok": False, "error": f"ALS template parse failed: {exc}"}

    # Mark generator without breaking Live's Creator version parse
    root.set("Creator", "Ableton Live 11.3.21")
    root.set("Revision", "reroll-als-export")

    ls = root.find("LiveSet")
    if ls is None:
        return {"ok": False, "error": "ALS template missing LiveSet"}

    tracks_el = ls.find("Tracks")
    if tracks_el is None:
        return {"ok": False, "error": "ALS template missing Tracks"}

    # Prototype AudioTrack only — drop returns (sends stripped later)
    prototype: ET.Element | None = None
    for t in list(tracks_el):
        if t.tag == "AudioTrack" and prototype is None:
            prototype = deepcopy(t)
        tracks_el.remove(t)

    if prototype is None:
        return {"ok": False, "error": "ALS template has no AudioTrack prototype"}

    # Clean prototype before cloning — each stem track starts with zero sends
    _strip_sends_from_element(prototype)

    # Tempo
    bpm_f = max(20.0, min(999.0, float(bpm or 140)))
    for tempo in ls.iter("Tempo"):
        man = tempo.find("Manual")
        if man is not None:
            man.set("Value", str(bpm_f))

    bars_i = max(1, min(32, int(bars or 4)))
    beat_length = float(bars_i * 4)  # 4/4: 4 beats per bar

    written_samples: list[str] = []
    next_track_id = 10
    next_free_id = 100
    colors = [0, 12, 24, 36, 48, 60, 9, 21, 33, 45]

    for i, item in enumerate(audio_files):
        src = Path(str(item.get("abs_path") or ""))
        if not src.is_file():
            continue
        fname = str(item.get("name") or src.name)
        # Keep basename only inside Samples/Imported
        safe_name = Path(fname).name
        dest = samples_dir / safe_name
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        written_samples.append(str(dest.resolve()))

        track_name = str(item.get("track") or Path(safe_name).stem)[:40]
        rel = f"Samples/Imported/{safe_name}"

        track = deepcopy(prototype)
        next_free_id = _configure_audio_track(
            track,
            track_id=next_track_id,
            name=track_name,
            rel_sample=rel,
            abs_sample=dest,
            beat_length=beat_length,
            color=colors[i % len(colors)],
        )
        tracks_el.append(track)
        next_track_id += 1

    if not written_samples:
        return {"ok": False, "error": "No audio stems available for .als project"}

    # Stable, easy-to-spot names in Explorer
    als_name = f"{display}.als"
    als_path = project_dir / als_name

    # Final pass: never ship Live-12-only classes (MidiEditorLaneModel etc.)
    _strip_unknown_live_nodes(root)

    # Session slots must match scene count on EVERY ClipSlotList in the set
    slot_info = _normalize_session_slots(root, n_slots=1)

    # Zero returns + zero sends (Live rejects any send/return count mismatch)
    send_info = _strip_returns_and_sends(root)
    try:
        _assert_clean_sends(root)
        _assert_slot_counts(root)
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}

    # NextPointeeId must be STRICTLY greater than every Id= in the whole set.
    max_id = max(_max_id_in_tree(root), int(next_free_id or 0), int(next_track_id or 0) * 1000)
    next_pointee = max(max_id + 10_000, 100_000)
    for npi in root.iter("NextPointeeId"):
        npi.set("Value", str(next_pointee))

    xml_body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if not xml_body.startswith(b"<?xml"):
        xml_body = b'<?xml version="1.0" encoding="UTF-8"?>\n' + xml_body

    body_txt = xml_body.decode("utf-8")
    body_txt, n_sub = re.subn(
        r'(<NextPointeeId\b[^>]*\bValue=")(\d+)(")',
        rf"\g<1>{next_pointee}\3",
        body_txt,
        count=8,
    )
    # Belt-and-suspenders: scrub send/return tags from serialized XML
    body_txt, scrub = _xml_force_strip_returns_sends(body_txt)
    xml_body = body_txt.encode("utf-8")

    try:
        check_root = ET.fromstring(body_txt)
        _assert_clean_sends(check_root)
        _assert_slot_counts(check_root)
    except Exception as exc:
        return {"ok": False, "error": f"ALS serialize verify failed: {exc}"}

    with gzip.open(als_path, "wb", compresslevel=6) as gz:
        gz.write(xml_body)

    # Re-read from disk — same bytes Live will open
    try:
        disk_xml = gzip.decompress(als_path.read_bytes()).decode("utf-8")
        disk_root = ET.fromstring(disk_xml)
        _assert_clean_sends(disk_root)
        _assert_slot_counts(disk_root)
        disk_npi = disk_root.find("LiveSet").find("NextPointeeId")
        disk_npi_v = disk_npi.get("Value") if disk_npi is not None else "?"
        n_sc = len(list(disk_root.find("LiveSet").find("Scenes")))
        list_sizes = sorted(
            {
                sum(1 for s in csl if s.tag == "ClipSlot")
                for csl in disk_root.iter("ClipSlotList")
            }
        )
    except Exception as exc:
        return {"ok": False, "error": f"ALS disk verify failed: {exc}"}

    print(
        f"[reroll] ALS OK path={als_path} NextPointeeId={disk_npi_v} "
        f"scenes={n_sc} slot_list_sizes={list_sizes} "
        f"(max Id={max_id}, npi_subs={n_sub}, scrub={scrub}, lists={slot_info.get('lists')}) "
        f"returns_removed={send_info.get('returns_removed')} "
        f"sends_removed={send_info.get('send_holders_removed')} "
        f"send_pre_removed={send_info.get('send_pre_removed')}",
        flush=True,
    )

    # Extra obvious pointer file when .als shares the stems folder
    readme_als = project_dir / "OPEN_THIS_IN_ABLETON.txt"
    try:
        readme_als.write_text(
            "\n".join(
                [
                    f"Ableton Live Set: {als_name}",
                    "",
                    "Double-click the .als file (same folder) to open in Live.",
                    "Stems used by the set are under Samples\\Imported\\",
                    "Flat .wav files in this folder are for drag-and-drop.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    except OSError:
        pass

    return {
        "ok": True,
        "project_dir": str(project_dir.resolve()),
        "als_path": str(als_path.resolve()),
        "als_name": als_name,
        "samples": written_samples,
        "tracks": len(written_samples),
        "bpm": bpm_f,
        "bars": bars_i,
        "next_pointee_id": next_pointee,
        "max_id": max_id,
    }
