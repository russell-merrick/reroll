"""Rebuild live_set_template.xml from Ableton DefaultLiveSet + Live 12.2 clip.

Sources (installed Ableton + local crash dump, all on this machine):
  - DefaultLiveSet.als — clean factory skeleton
  - user Live 12.2.6 AudioClip — matching schema for the user's Live version
"""

from __future__ import annotations

import gzip
from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "backend" / "templates" / "live_set_template.xml"

DEFAULT_SET = Path(
    r"C:\ProgramData\Ableton\.Live 12 Suite_updated\Resources\Builtin\Templates\DefaultLiveSet.als"
)
# Prefer a real Live 12.2.6 clip (same major schema the user opens with)
CLIP_SRC = Path(
    r"C:\Users\russe\AppData\Roaming\Ableton\Live 12.2.6\Preferences\Crash"
    r"\2025_11_07__17_08_06_BaseFiles\2025-10-30-drugged-out-vibin-in-g.als"
)


def _clear(el: ET.Element | None) -> None:
    if el is None:
        return
    for c in list(el):
        el.remove(c)


def _blank_clip(clip: ET.Element) -> None:
    for el in clip.iter("RelativePath"):
        el.set("Value", "Samples/Imported/PLACEHOLDER.wav")
    for el in clip.iter("Path"):
        el.set("Value", "")
    for el in clip.iter("OriginalFileSize"):
        el.set("Value", "0")
    for el in clip.iter("OriginalCrc"):
        el.set("Value", "0")
    for el in clip.iter("LivePackName"):
        el.set("Value", "")
    for el in clip.iter("LivePackId"):
        el.set("Value", "")
    for fr in clip.iter("FileRef"):
        for child in list(fr):
            if child.tag == "SourceHint":
                fr.remove(child)
        rpt = fr.find("RelativePathType")
        if rpt is not None:
            rpt.set("Value", "6")
    name = clip.find("Name")
    if name is not None:
        name.set("Value", "PLACEHOLDER")
    clip.set("Time", "0")
    for tag, val in (
        ("CurrentStart", "0"),
        ("CurrentEnd", "16"),
        ("IsWarped", "true"),
        ("Disabled", "false"),
        ("IsInKey", "false"),
        ("TakeId", "1"),
    ):
        el = clip.find(tag)
        if el is not None:
            el.set("Value", val)
    si = clip.find("ScaleInformation")
    if si is not None:
        r, n = si.find("Root"), si.find("Name")
        if r is not None:
            r.set("Value", "0")
        if n is not None:
            n.set("Value", "0")
    loop = clip.find("Loop")
    if loop is not None:
        for tag, val in (
            ("LoopOn", "true"),
            ("LoopStart", "0"),
            ("LoopEnd", "16"),
            ("StartRelative", "0"),
            ("OutMarker", "16"),
            ("HiddenLoopStart", "0"),
            ("HiddenLoopEnd", "16"),
        ):
            el = loop.find(tag)
            if el is not None and "Value" in el.attrib:
                el.set("Value", val)
    markers = clip.find("WarpMarkers")
    if markers is not None:
        _clear(markers)
        ET.SubElement(markers, "WarpMarker", Id="0", SecTime="0", BeatTime="0")
        ET.SubElement(markers, "WarpMarker", Id="1", SecTime="1", BeatTime="1")
    for sr in clip.iter("SampleRef"):
        sc = sr.find("SourceContext")
        if sc is not None:
            _clear(sc)
            sc.attrib.clear()
        for tag, val in (
            ("DefaultDuration", "44100"),
            ("DefaultSampleRate", "44100"),
            ("SamplesToAutoWarp", "1"),
        ):
            el = sr.find(tag)
            if el is not None:
                el.set("Value", val)


def _set_slot_clip(slot: ET.Element, clip: ET.Element | None) -> None:
    """DefaultLiveSet slots: ClipSlot/ClipSlot/Value[/AudioClip]."""
    inner = slot.find("ClipSlot")
    if inner is None:
        inner = ET.SubElement(slot, "ClipSlot")
    val = inner.find("Value")
    if val is None:
        val = ET.SubElement(inner, "Value")
    for c in list(val):
        val.remove(c)
    if clip is not None:
        val.append(deepcopy(clip))


def main() -> None:
    if not DEFAULT_SET.is_file():
        raise SystemExit(f"missing: {DEFAULT_SET}")
    if not CLIP_SRC.is_file():
        raise SystemExit(f"missing: {CLIP_SRC}")

    root = ET.fromstring(gzip.open(DEFAULT_SET, "rb").read().decode("utf-8", "replace"))
    ls = root.find("LiveSet")
    tracks_el = ls.find("Tracks")

    proto = None
    for t in list(tracks_el):
        if t.tag == "AudioTrack" and proto is None:
            proto = deepcopy(t)
        tracks_el.remove(t)
    assert proto is not None

    clip_root = ET.fromstring(gzip.open(CLIP_SRC, "rb").read().decode("utf-8", "replace"))
    clip_proto = deepcopy(next(clip_root.iter("AudioClip")))
    _blank_clip(clip_proto)

    # Clear arrangement
    for seq in proto.iter("MainSequencer"):
        sample = seq.find("Sample")
        if sample is None:
            continue
        arr = sample.find("ArrangerAutomation")
        if arr is not None:
            _clear(arr.find("Events"))

    # 1 scene worth of slots on every sequencer
    for seq in proto.iter():
        if seq.tag not in ("MainSequencer", "FreezeSequencer"):
            continue
        csl = seq.find("ClipSlotList")
        if csl is None:
            continue
        shell = None
        for s in list(csl):
            if s.tag == "ClipSlot":
                shell = deepcopy(s)
                break
        _clear(csl)
        if shell is None:
            continue
        shell.set("Id", "0")
        put_clip = seq.tag == "MainSequencer"
        _set_slot_clip(shell, clip_proto if put_clip else None)
        csl.append(shell)

    for el in proto.iter("TrackGroupId"):
        el.set("Value", "-1")
    for el in proto.iter("LinkedTrackGroupId"):
        el.set("Value", "-1")
    for routing in proto.iter("AudioOutputRouting"):
        t = routing.find("Target")
        if t is not None:
            t.set("Value", "AudioOut/Master")
        u = routing.find("UpperDisplayString")
        if u is not None:
            u.set("Value", "Master")
    for sends in proto.iter("Sends"):
        _clear(sends)

    name = proto.find("Name")
    if name is not None:
        for tag in ("EffectiveName", "UserName", "MemorizedFirstClipName"):
            el = name.find(tag)
            if el is not None:
                el.set("Value", "Track")
    color = proto.find("Color")
    if color is not None:
        color.set("Value", "0")
    proto.set("Id", "10")

    # Do NOT invent ArrangementClipsListWrapper — factory AudioTrack lacks it
    for tag in ("ArrangementClipsListWrapper", "TakeLanesListWrapper"):
        el = proto.find(tag)
        if el is not None:
            # keep if factory had it; Default doesn't
            pass

    tracks_el.append(proto)

    scenes = ls.find("Scenes")
    if scenes is not None:
        first = True
        for s in list(scenes):
            if first:
                s.set("Id", "0")
                ne = s.find("Name")
                if ne is not None:
                    ne.set("Value", "Reroll")
                first = False
            else:
                scenes.remove(s)

    sp = ls.find("SendsPre")
    if sp is not None:
        _clear(sp)
    for t in (ls.find("MainTrack"), ls.find("PreHearTrack")):
        if t is None:
            continue
        for sends in t.iter("Sends"):
            _clear(sends)
        # Normalize Main/PreHear slot lists to 1 empty slot
        for csl in t.iter("ClipSlotList"):
            shell = None
            for s in list(csl):
                if s.tag == "ClipSlot":
                    shell = deepcopy(s)
                    break
            _clear(csl)
            if shell is not None:
                shell.set("Id", "0")
                _set_slot_clip(shell, None)
                csl.append(shell)

    for tag in ("ExpressionLanes", "ContentLanes", "DetailClipKeyMidis"):
        el = ls.find(tag)
        if el is not None:
            ls.remove(el)

    # Align header to Live 12.2.6 (user's working version)
    root.set("Creator", "Ableton Live 12.2.6")
    root.set("MinorVersion", "12.0_12203")
    root.set("SchemaChangeCount", "3")
    root.set("Revision", "reroll-from-defaultliveset")

    max_p = 0
    for el in root.iter("Pointee"):
        try:
            max_p = max(max_p, int(el.get("Id") or "0"))
        except ValueError:
            pass
    npi = ls.find("NextPointeeId")
    if npi is not None:
        npi.set("Value", str(max(max_p + 1000, 100000)))

    xml = ET.tostring(root, encoding="unicode")
    if not xml.startswith("<?xml"):
        xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml
    OUT.write_text(xml, encoding="utf-8")
    print(f"wrote {OUT} bytes={OUT.stat().st_size}")
    print("clips", sum(1 for _ in root.iter("AudioClip")))
    print("returns", sum(1 for _ in root.iter("ReturnTrack")))
    print("slot structure OK")


if __name__ == "__main__":
    main()
