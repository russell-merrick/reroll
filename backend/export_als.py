"""Write an Ableton Live Set project folder (.als + Samples) from exported stems.

.als files are gzip-compressed XML. We clone a sanitized single-track template
(backend/templates/live_set_template.xml) per audio stem so Live can open a
real project instead of only drag-and-drop clips.
"""

from __future__ import annotations

import gzip
import os
import re
import shutil
import wave
from copy import deepcopy
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "live_set_template.xml"

# RelativePathType 6 = project-relative (Live 12 user sets; matches real FileRefs)
_PROJECT_RELATIVE = "6"

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


def _normalize_track_grouping(root: ET.Element) -> None:
    """
    Stem exports are flat (no GroupTrack). Live errors with
    \"track grouping corrupt\" if any track still has TrackGroupId
    pointing at a missing group, or routes AudioOut/GroupTrack.
    """
    # Drop any GroupTrack leftovers
    ls = root.find("LiveSet")
    tracks_el = ls.find("Tracks") if ls is not None else None
    if tracks_el is not None:
        for t in list(tracks_el):
            if t.tag == "GroupTrack":
                tracks_el.remove(t)

    for el in root.iter("TrackGroupId"):
        if "Value" in el.attrib:
            el.set("Value", "-1")
    for el in root.iter("LinkedTrackGroupId"):
        if "Value" in el.attrib:
            el.set("Value", "-1")

    # Empty LinkedTrackGroups container if present
    if ls is not None:
        ltg = ls.find("LinkedTrackGroups")
        if ltg is not None:
            for c in list(ltg):
                ltg.remove(c)

    # Audio routed into a group that no longer exists → Master
    for routing in root.iter("AudioOutputRouting"):
        target = routing.find("Target")
        if target is None:
            continue
        val = (target.get("Value") or "").strip()
        if "GroupTrack" in val or val in ("", "AudioOut/None"):
            target.set("Value", "AudioOut/Master")
            upper = routing.find("UpperDisplayString")
            if upper is not None:
                upper.set("Value", "Master")
            lower = routing.find("LowerDisplayString")
            if lower is not None:
                lower.set("Value", "")


# Live 12.2+ ScaleInformation.Name is an int index, not "Major"/"Minor" strings.
# Older templates use RootNote + string Name → Live error:
#   "unexpected value for int node: major"
_SCALE_NAME_TO_ID = {
    "major": "0",
    "maj": "0",
    "minor": "5",
    "min": "5",
    "dorian": "1",
    "mixolydian": "2",
    "lydian": "3",
    "phrygian": "4",
    "locrian": "6",
    "whole tone": "7",
    "half-whole dim": "8",
    "whole-half dim": "9",
    "minor blues": "10",
    "minor pentatonic": "11",
    "major pentatonic": "12",
    "harmonic minor": "13",
    "harmonic major": "14",
    "dorian #4": "15",
    "phrygian dominant": "16",
    "melodic minor": "17",
    "l melodic minor": "18",
    "super locrian": "19",
    "8-tone spanish": "20",
    "bhairav": "21",
    "hungarian minor": "22",
    "hirajoshi": "23",
    "in-sen": "24",
    "iwato": "25",
    "kumoi": "26",
    "pelog": "27",
    "spanish": "28",
}


def _scale_name_to_id(raw: str | None) -> str:
    """Map scale name string or int-ish value → Live 12 int id string."""
    if raw is None or raw == "":
        return "0"
    s = str(raw).strip()
    try:
        return str(int(s))
    except ValueError:
        pass
    return _SCALE_NAME_TO_ID.get(s.lower(), "0")


def _normalize_scale_information(root: ET.Element) -> None:
    """
    Live 12.2 clip + LiveSet ScaleInformation:

      <ScaleInformation>
        <Root Value="0" />
        <Name Value="0" />   <!-- int scale index, NOT "Major" -->
      </ScaleInformation>

    Pre-12.2 templates used RootNote + string Name ("Major"), which Live 12.2
    rejects as: unexpected value for int node: major
    """
    for si in root.iter("ScaleInformation"):
        root_note = si.find("RootNote")
        root_el = si.find("Root")
        if root_note is not None:
            val = root_note.get("Value", "0")
            if root_el is None:
                root_note.tag = "Root"
                root_el = root_note
            else:
                if not root_el.get("Value"):
                    root_el.set("Value", val)
                si.remove(root_note)
        if root_el is None:
            root_el = ET.Element("Root", Value="0")
            si.insert(0, root_el)
        try:
            root_el.set("Value", str(int(float(root_el.get("Value") or "0"))))
        except (TypeError, ValueError):
            root_el.set("Value", "0")

        name_el = si.find("Name")
        if name_el is None:
            name_el = ET.Element("Name", Value="0")
            si.append(name_el)
        name_el.set("Value", _scale_name_to_id(name_el.get("Value")))


def _beat_str(v: float) -> str:
    """Format beat times the way Live writes them (no trailing .0 when whole)."""
    f = float(v)
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    return repr(float(f))


def _load_template(path: Path) -> ET.Element:
    raw = path.read_text(encoding="utf-8")
    # Live 12 Master bus rename — keep Master for broader open compatibility
    raw = raw.replace("AudioOut/Main", "AudioOut/Master")
    root = ET.fromstring(raw)
    _strip_unknown_live_nodes(root)
    _normalize_scale_information(root)
    _normalize_track_grouping(root)
    # Live 12 header (user machines are on Live 12; still opens fine)
    root.set("MajorVersion", "5")
    root.set("MinorVersion", "12.0_12203")
    root.set("SchemaChangeCount", "3")
    root.set("Creator", "Ableton Live 12.2.6")
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


# Id attrs that are *list indices* (may repeat across the document).
# Everything else with Id= is treated as a global pointee-space id.
_LIST_LOCAL_ID_TAGS = frozenset(
    {
        "ClipSlot",
        "WarpMarker",
        "Scene",
        "AutomationLane",
        "AutomationEnvelope",
        "EnumEvent",
        "FloatEvent",
        "BoolEvent",
        "Breakpoint",
        "TrackSendHolder",
        "SendPreBool",
        "FileRef",
        "FilePresetRef",
        "BranchSourceContext",
        "MidiEditorLaneModel",
        "RemoteableTimeSignature",
        "RemoteableFloat",
        "AudioClip",
        "MidiClip",
        "AudioSequencer",
        "GroupTrackSlot",
        "KeyTrack",
        "Notes",
        "KeyTracks",
        "ExpressionLane",
        "ContentLane",
        "Locator",
        "ArpeggiateAlgorithm",
        "ScaleInformation",  # no Id usually
    }
)


def _renumber_ids(track: ET.Element, base_id: int) -> int:
    """
    Per-track pass: unique-ify non-list-local Ids under one track clone.

    Prefer ``_finalize_unique_pointee_ids`` on the whole document afterward.
    """
    n = base_id
    for el in track.iter():
        if "Id" not in el.attrib:
            continue
        if el.tag in _LIST_LOCAL_ID_TAGS:
            continue
        try:
            int(el.attrib["Id"])
        except (TypeError, ValueError):
            continue
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


def _clear_automation_envelopes(root: ET.Element) -> int:
    """Drop AutomationEnvelope nodes (stem export needs none; avoids dangling PointeeId)."""
    n = 0
    for parent in list(root.iter()):
        for child in list(parent):
            if child.tag == "AutomationEnvelope":
                parent.remove(child)
                n += 1
    return n


def _finalize_unique_pointee_ids(root: ET.Element) -> dict[str, int]:
    """
    Live error: \"non-unique pointee IDs\".

    Factory sets give every RemoteableObject a unique Id (Pointee, AutomationTarget,
    ModulationTarget, Track, …). Cloning AudioTracks without reassigning those
    Ids leaves triples of the same AutomationTarget Id → Live refuses the set.

    List-local Ids (ClipSlot 0..n-1, WarpMarker, Scene, …) must NOT be uniquified.
    """
    # 1) Clear envelopes that reference track/device pointees we may rewrite
    n_env = _clear_automation_envelopes(root)

    # 2) Assign unique Ids to every non-list-local Id= in document order
    n = 1
    n_reassigned = 0
    for el in root.iter():
        if "Id" not in el.attrib:
            continue
        if el.tag in _LIST_LOCAL_ID_TAGS:
            continue
        try:
            int(el.attrib["Id"])
        except (TypeError, ValueError):
            continue
        el.set("Id", str(n))
        n += 1
        n_reassigned += 1

    # 3) Explicit <Pointee Id> must be unique (covered above) — also ensure
    #    every Pointee has an Id
    for p in root.iter("Pointee"):
        if "Id" not in p.attrib:
            p.set("Id", str(n))
            n += 1
            n_reassigned += 1

    # 4) NextPointeeId strictly above every assigned id
    next_pointee = n + 100
    for npi in root.iter("NextPointeeId"):
        npi.set("Value", str(next_pointee))

    # 5) Verify no duplicate Pointee Ids
    seen: dict[str, int] = {}
    dups = 0
    for p in root.iter("Pointee"):
        pid = p.get("Id")
        if pid is None:
            continue
        seen[pid] = seen.get(pid, 0) + 1
    dups = sum(1 for c in seen.values() if c > 1)

    # 6) Verify no duplicate non-list-local Ids
    global_ids: dict[str, int] = {}
    for el in root.iter():
        if "Id" not in el.attrib or el.tag in _LIST_LOCAL_ID_TAGS:
            continue
        i = el.attrib["Id"]
        global_ids[i] = global_ids.get(i, 0) + 1
    global_dups = sum(1 for c in global_ids.values() if c > 1)

    return {
        "next_pointee_id": next_pointee,
        "reassigned": n_reassigned,
        "envelopes_cleared": n_env,
        "pointee_dups": dups,
        "global_dups": global_dups,
        "max_id": n - 1,
    }


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
                sc.set("Id", str(i))
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


def _session_audio_clips(track: ET.Element) -> list[ET.Element]:
    """AudioClips that live in Session ClipSlots (not arrangement Events)."""
    clips: list[ET.Element] = []
    for ms in track.iter("MainSequencer"):
        csl = ms.find("ClipSlotList")
        if csl is None:
            continue
        for clip in csl.iter("AudioClip"):
            clips.append(clip)
        break
    return clips


def _ensure_live12_clip_fields(clip: ET.Element) -> None:
    """Live 12 arrangement clips include IsInKey + ScaleInformation."""
    if clip.find("IsInKey") is None:
        take = clip.find("TakeId")
        el = ET.Element("IsInKey", Value="false")
        if take is not None:
            idx = list(clip).index(take) + 1
            clip.insert(idx, el)
        else:
            clip.append(el)
    if clip.find("ScaleInformation") is None:
        si = ET.Element("ScaleInformation")
        ET.SubElement(si, "Root", Value="0")
        ET.SubElement(si, "Name", Value="0")
        is_in_key = clip.find("IsInKey")
        if is_in_key is not None:
            idx = list(clip).index(is_in_key) + 1
            clip.insert(idx, si)
        else:
            clip.append(si)


def _fix_sampleref_live12(
    clip: ET.Element,
    *,
    rel_sample: str,
    abs_sample: Path,
    frames: int,
    rate: int,
    size: int,
) -> None:
    """
    Match real Live 12.2 FileRef / SampleRef shape:

      FileRef: RelativePathType, RelativePath, Path, Type, LivePackName,
               LivePackId, OriginalFileSize, OriginalCrc
      SampleRef: FileRef, LastModDate, SourceContext (empty), SampleUsageHint,
                 DefaultDuration, DefaultSampleRate, SamplesToAutoWarp

    Do NOT invent SourceHint — real 12.2 sets do not have it.
    """
    rel = rel_sample.replace("\\", "/")
    abs_path = str(abs_sample.resolve()).replace("\\", "/")
    mtime = "0"
    try:
        mtime = str(int(abs_sample.stat().st_mtime))
    except OSError:
        pass

    path_type = _PROJECT_RELATIVE  # "6"

    for fr in clip.iter("FileRef"):
        # Remove non-schema kids (SourceHint was a prior mistaken inject)
        for child in list(fr):
            if child.tag == "SourceHint":
                fr.remove(child)
        for el in fr:
            if el.tag == "RelativePathType":
                el.set("Value", path_type)
            elif el.tag == "RelativePath":
                el.set("Value", rel)
            elif el.tag == "Path":
                el.set("Value", abs_path)
            elif el.tag == "Type":
                el.set("Value", "1")
            elif el.tag == "OriginalFileSize":
                el.set("Value", str(size))
            elif el.tag == "OriginalCrc":
                el.set("Value", el.get("Value") or "0")
            elif el.tag == "LivePackName":
                el.set("Value", "")
            elif el.tag == "LivePackId":
                el.set("Value", "")

    for sr in clip.iter("SampleRef"):
        # Flatten SourceContext to empty element (Live 12.2 style)
        sc = sr.find("SourceContext")
        if sc is not None:
            for child in list(sc):
                sc.remove(child)
            sc.attrib.clear()
            sc.text = None
        else:
            sc = ET.Element("SourceContext")
            lmd = sr.find("LastModDate")
            if lmd is not None:
                sr.insert(list(sr).index(lmd) + 1, sc)
            else:
                sr.insert(0, sc)

        lmd = sr.find("LastModDate")
        if lmd is not None:
            lmd.set("Value", mtime)
        dd = sr.find("DefaultDuration")
        if dd is not None:
            dd.set("Value", str(frames))
        dsr = sr.find("DefaultSampleRate")
        if dsr is not None:
            dsr.set("Value", str(rate))
        if sr.find("SamplesToAutoWarp") is None:
            saw = ET.Element("SamplesToAutoWarp", Value="1")
            dsr_el = sr.find("DefaultSampleRate")
            if dsr_el is not None:
                sr.insert(list(sr).index(dsr_el) + 1, saw)
            else:
                sr.append(saw)
        else:
            _set_value(sr, "SamplesToAutoWarp", "1")


def _set_clip_timing(
    clip: ET.Element,
    *,
    name: str,
    beat_length: float,
    sec_length: float,
    arrangement: bool = False,
    arr_time: float = 0.0,
    bpm: float = 140.0,
) -> None:
    """
    Length, loop, and warp markers.

    Session: warped clip-local 0…beat_length (works for Session launching).
    Arrangement (Live 12): absolute Time/CurrentStart/CurrentEnd. Prefer
    unwarped clips matching factory lesson sets so Live draws waveforms.
    """
    t0 = float(arr_time) if arrangement else 0.0

    # Session + arrangement: keep WARPED clips with matching SecTime/BeatTime.
    # Unwarped arrangement with CurrentEnd >> sample length hard-crashes some Live builds.
    length_s = _beat_str(beat_length)
    start_s = _beat_str(t0)
    end_s = _beat_str(t0 + float(beat_length))
    sec = max(0.001, float(sec_length))

    clip.set("Time", start_s if arrangement else "0")
    _set_value(clip, "Name", name)
    if arrangement:
        # Arrangement uses absolute song time for CurrentStart/End
        _set_value(clip, "CurrentStart", start_s)
        _set_value(clip, "CurrentEnd", end_s)
    else:
        _set_value(clip, "CurrentStart", "0")
        _set_value(clip, "CurrentEnd", length_s)
    _set_value(clip, "IsWarped", "true")
    _set_value(clip, "Disabled", "false")
    _set_value(clip, "TakeId", "1")

    loop = clip.find("Loop")
    if loop is not None:
        # Loop region is always clip-local 0…beat_length
        _set_value(loop, "LoopOn", "true")
        _set_value(loop, "LoopStart", "0")
        _set_value(loop, "LoopEnd", length_s)
        _set_value(loop, "StartRelative", "0")
        _set_value(loop, "OutMarker", length_s)
        for tag in ("HiddenLoopStart", "HiddenLoopEnd"):
            h = loop.find(tag)
            if h is not None and "Value" in h.attrib:
                h.set("Value", "0" if "Start" in tag else length_s)

    markers = clip.find("WarpMarkers")
    if markers is not None:
        for child in list(markers):
            markers.remove(child)
        ET.SubElement(markers, "WarpMarker", Id="0", SecTime="0", BeatTime="0")
        ET.SubElement(
            markers,
            "WarpMarker",
            Id="1",
            SecTime=repr(float(sec)),
            BeatTime=length_s,
        )

    scroller = clip.find("ScrollerTimePreserver")
    if scroller is not None:
        _set_value(scroller, "LeftTime", "0")
        _set_value(scroller, "RightTime", _beat_str(beat_length))

    _ensure_live12_clip_fields(clip)


def _place_arrangement_clips(
    track: ET.Element,
    *,
    beat_length: float,
    sec_length: float,
    name: str,
    bpm: float = 140.0,
    rel_sample: str = "",
    abs_sample: Path | None = None,
    frames: int = 0,
    rate: int = 44100,
    size: int = 0,
) -> int:
    """
    Session clips alone do not appear on the Arrangement timeline.

    Arrangement audio lives under:
      MainSequencer/Sample/ArrangerAutomation/Events  →  AudioClip Time=\"…\"

    Live 12: absolute CurrentStart/CurrentEnd, flat SampleRef, often unwarped.
    """
    session_clips = _session_audio_clips(track)
    if not session_clips:
        return 0

    placed = 0
    for ms in track.iter("MainSequencer"):
        sample = ms.find("Sample")
        if sample is None:
            sample = ET.SubElement(ms, "Sample")
        arr = sample.find("ArrangerAutomation")
        if arr is None:
            arr = ET.SubElement(sample, "ArrangerAutomation")
        events = arr.find("Events")
        if events is None:
            events = ET.SubElement(arr, "Events")
        for child in list(events):
            events.remove(child)

        arr_clip = deepcopy(session_clips[0])
        _set_clip_timing(
            arr_clip,
            name=name,
            beat_length=beat_length,
            sec_length=sec_length,
            arrangement=True,
            arr_time=0.0,
            bpm=bpm,
        )
        if abs_sample is not None and rel_sample:
            _fix_sampleref_live12(
                arr_clip,
                rel_sample=rel_sample,
                abs_sample=abs_sample,
                frames=frames or int(sec_length * rate),
                rate=rate or 44100,
                size=size,
            )
        events.append(arr_clip)
        placed += 1

        for tag, val in (
            ("SavedPlayingSlot", "-1"),
            ("SavedPlayingOffset", "0"),
            ("NeedArrangerRefreeze", "false"),
        ):
            for el in track.iter(tag):
                if "Value" in el.attrib:
                    el.set("Value", val)
        # Do not invent ArrangementClipsListWrapper / TakeLanesListWrapper —
        # factory DefaultLiveSet AudioTracks omit them; injecting crashed Live.
        break
    return placed


def _configure_transport(ls: ET.Element, *, beat_length: float) -> None:
    """Enable the arrangement loop brace over [0, beat_length) beats (e.g. 4 bars)."""
    beat_s = _beat_str(beat_length)
    for transport in ls.iter("Transport"):
        _set_value(transport, "LoopOn", "true")
        _set_value(transport, "LoopStart", "0")
        _set_value(transport, "LoopLength", beat_s)
        _set_value(transport, "LoopIsSongStart", "true")
        _set_value(transport, "CurrentTime", "0")
    # Selection / follow region (LiveSet-level TimeSelection)
    for ts in ls.findall("TimeSelection"):
        _set_value(ts, "AnchorTime", "0")
        _set_value(ts, "OtherTime", beat_s)
    # Arrangement overview zoom so the loop is visible
    for nav in ls.iter("SequencerNavigator"):
        helper = nav.find("BeatTimeHelper")
        if helper is not None:
            zoom = helper.find("CurrentZoom")
            # Smaller zoom value ≈ more zoomed out in many Live versions
            if zoom is not None:
                zoom.set("Value", "0.35")
        sp = nav.find("ScrollerPos")
        if sp is not None:
            sp.set("X", "0")
            sp.set("Y", "0")


def _configure_audio_track(
    track: ET.Element,
    *,
    track_id: int,
    name: str,
    rel_sample: str,
    abs_sample: Path,
    beat_length: float,
    color: int,
    bpm: float = 140.0,
) -> int:
    """Mutate a cloned AudioTrack for one stem. Returns next free Id."""
    track.set("Id", str(track_id))
    frames, rate = _wav_frames_and_rate(abs_sample)
    sec_length = float(frames) / float(rate or 44100)
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

    abs_fwd = str(abs_sample.resolve()).replace("\\", "/")
    rel_fwd = rel_sample.replace("\\", "/")

    # Sample path refs (session + any existing refs on the track)
    for el in track.iter("RelativePath"):
        el.set("Value", rel_fwd)
    for el in track.iter("RelativePathType"):
        # Live 12.2 project samples use type 6 (not classic 3)
        el.set("Value", _PROJECT_RELATIVE)
    for el in track.iter("Path"):
        el.set("Value", abs_fwd)
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

    # Session clip timing first (clip-local 0…beat_length)
    for clip in _session_audio_clips(track):
        _set_clip_timing(
            clip,
            name=name,
            beat_length=beat_length,
            sec_length=sec_length,
            arrangement=False,
            bpm=bpm,
        )

    # Arrangement placement is done once in write_als_project (final pass).

    # Unique Pointee Ids only (ClipSlot Ids stay 0..n-1)
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

    # Mark generator (Live 12 Creator string)
    root.set("Creator", "Ableton Live 12.2.6")
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
    # Arrangement loop brace + playhead (Session clips alone stay on session grid)
    _configure_transport(ls, beat_length=beat_length)

    written_samples: list[str] = []
    # Per-track sample metadata for arrangement final pass
    track_meta: list[dict[str, Any]] = []
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
        fr, rt = _wav_frames_and_rate(dest)
        try:
            sz = dest.stat().st_size
        except OSError:
            sz = 0

        track = deepcopy(prototype)
        next_free_id = _configure_audio_track(
            track,
            track_id=next_track_id,
            name=track_name,
            rel_sample=rel,
            abs_sample=dest,
            beat_length=beat_length,
            color=colors[i % len(colors)],
            bpm=bpm_f,
        )
        tracks_el.append(track)
        track_meta.append(
            {
                "name": track_name,
                "rel": rel,
                "abs": dest,
                "frames": fr,
                "rate": rt,
                "size": sz,
                "sec": float(fr) / float(rt or 44100),
            }
        )
        next_track_id += 1

    if not written_samples:
        return {"ok": False, "error": "No audio stems available for .als project"}

    # Stable, easy-to-spot names in Explorer
    als_name = f"{display}.als"
    als_path = project_dir / als_name

    # Final pass: never ship Live-12-only classes (MidiEditorLaneModel etc.)
    _strip_unknown_live_nodes(root)
    # Ensure every ScaleInformation uses int Name (Live 12.2 schema)
    _normalize_scale_information(root)
    # Flat track list — no dangling group membership
    _normalize_track_grouping(root)
    # Never ship invented FileRef kids (real Live 12.2 has no SourceHint)
    for fr in root.iter("FileRef"):
        for child in list(fr):
            if child.tag == "SourceHint":
                fr.remove(child)

    # Session slots must match scene count on EVERY ClipSlotList in the set
    slot_info = _normalize_session_slots(root, n_slots=1)

    # Session-only stems by default: arrangement AudioClip injection has caused
    # repeated Live hard-crashes ("serious program error"). Session clips in
    # scene 1 still open reliably; user can drag to arrangement in Live.
    # Set REROLL_ALS_ARRANGEMENT=1 to re-enable experimental arrangement clips.
    arr_placed = 0
    want_arrangement = os.environ.get("REROLL_ALS_ARRANGEMENT", "").strip() in (
        "1",
        "true",
        "yes",
    )
    audio_tracks = tracks_el.findall("AudioTrack")
    for ti, track in enumerate(audio_tracks):
        meta = track_meta[ti] if ti < len(track_meta) else {}
        tname = str(meta.get("name") or "stem")
        sec_len = float(meta.get("sec") or 1.0)
        if want_arrangement:
            arr_placed += _place_arrangement_clips(
                track,
                beat_length=beat_length,
                sec_length=sec_len,
                name=tname,
                bpm=bpm_f,
                rel_sample=str(meta.get("rel") or ""),
                abs_sample=meta.get("abs"),
                frames=int(meta.get("frames") or 0),
                rate=int(meta.get("rate") or 44100),
                size=int(meta.get("size") or 0),
            )
        else:
            # Ensure arrangement event list exists but is empty (factory shape)
            for ms in track.iter("MainSequencer"):
                sample = ms.find("Sample")
                if sample is None:
                    continue
                arr = sample.find("ArrangerAutomation")
                if arr is None:
                    continue
                events = arr.find("Events")
                if events is not None:
                    for child in list(events):
                        events.remove(child)
        track_base = (10 + ti) * 1000 + 1
        track.set("Id", str(10 + ti))
        next_free_id = _renumber_ids(track, track_base)
        track.set("Id", str(10 + ti))

    # Zero returns + zero sends (Live rejects any send/return count mismatch)
    send_info = _strip_returns_and_sends(root)
    try:
        _assert_clean_sends(root)
        _assert_slot_counts(root)
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}

    # Global unique pointee-space Ids (cloning tracks otherwise duplicates
    # AutomationTarget/ModulationTarget Ids → Live: "non-unique pointee IDs")
    pointee_info = _finalize_unique_pointee_ids(root)
    if pointee_info.get("pointee_dups") or pointee_info.get("global_dups"):
        return {
            "ok": False,
            "error": (
                f"ALS pointee uniquify failed: pointee_dups={pointee_info.get('pointee_dups')} "
                f"global_dups={pointee_info.get('global_dups')}"
            ),
        }
    next_pointee = int(pointee_info["next_pointee_id"])
    max_id = int(pointee_info["max_id"])

    # Re-assert list-local slot/scene Ids after global pass (untouched, but safe)
    for csl in root.iter("ClipSlotList"):
        for i, slot in enumerate(s for s in csl if s.tag == "ClipSlot"):
            slot.set("Id", str(i))
    scenes_el = ls.find("Scenes")
    if scenes_el is not None:
        for i, sc in enumerate(scenes_el):
            sc.set("Id", str(i))

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
        # Pointees unique on serialized tree
        pids = [p.get("Id") for p in check_root.iter("Pointee")]
        if len(pids) != len(set(pids)):
            return {"ok": False, "error": "ALS serialize has duplicate Pointee Ids"}
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

    # Count arrangement clips written to disk
    n_arr_clips = 0
    for track in disk_root.iter("AudioTrack"):
        for ms in track.iter("MainSequencer"):
            ev = ms.find("Sample/ArrangerAutomation/Events")
            if ev is not None:
                n_arr_clips += sum(1 for c in ev if c.tag == "AudioClip")

    print(
        f"[reroll] ALS OK path={als_path} NextPointeeId={disk_npi_v} "
        f"scenes={n_sc} slot_list_sizes={list_sizes} arr_clips={n_arr_clips} "
        f"(max Id={max_id}, npi_subs={n_sub}, scrub={scrub}, lists={slot_info.get('lists')}, "
        f"arr_placed={arr_placed}, pointee_reassigned={pointee_info.get('reassigned')}, "
        f"envelopes_cleared={pointee_info.get('envelopes_cleared')}) "
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
                    "Press Tab to switch Session ↔ Arrangement.",
                    "Arrangement: stems laid out from bar 1 (loop brace = full loop).",
                    "If clips look greyed out, click Back to Arrangement (▶←).",
                    "Session: scene 1 also has each stem for clip launching.",
                    "Stems: Samples\\Imported\\  ·  flat .wavs = drag-and-drop.",
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
