"""One-shot: build sanitized Live Set XML template from a local factory .als."""

from __future__ import annotations

import gzip
import sys
from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "backend" / "templates" / "live_set_template.xml"

DEFAULT_SRC = Path.home() / (
    "Documents/Ableton/Factory Packs/Granulator III/"
    "Ableton Folder Info/Sample Reference.als"
)


def main(src: Path) -> None:
    if not src.is_file():
        raise SystemExit(f"Source .als not found: {src}")

    root = ET.fromstring(gzip.decompress(src.read_bytes()).decode("utf-8"))
    root.set("MinorVersion", "11.0_11300")
    root.set("SchemaChangeCount", "3")
    root.set("Creator", "Ableton Live 11.3.21")
    root.set("Revision", "reroll-export-template")

    ls = root.find("LiveSet")
    assert ls is not None
    tracks = ls.find("Tracks")
    assert tracks is not None

    returns = [t for t in list(tracks) if t.tag == "ReturnTrack"]
    audio = tracks.find("AudioTrack")
    assert audio is not None
    at = deepcopy(audio)

    main_csl = None
    for csl in at.iter("ClipSlotList"):
        if any(list(s.iter("AudioClip")) for s in csl):
            main_csl = csl
            break
    assert main_csl is not None

    slots = list(main_csl)
    filled = [s for s in slots if list(s.iter("AudioClip"))]
    empty = [s for s in slots if not list(s.iter("AudioClip"))]
    keep = filled[:1] + empty[:7]
    for s in list(main_csl):
        main_csl.remove(s)
    for s in keep:
        main_csl.append(s)

    for el in at.iter():
        if el.tag == "RelativePath" and "Value" in el.attrib:
            el.set("Value", "Samples/Imported/PLACEHOLDER.wav")
        if el.tag == "Path" and "Value" in el.attrib:
            el.set("Value", "")
        if el.tag in ("LivePackName", "LivePackId", "BrowserContentPath") and "Value" in el.attrib:
            el.set("Value", "")
        if el.tag == "OriginalFileSize" and "Value" in el.attrib:
            el.set("Value", "0")
        if el.tag == "OriginalCrc" and "Value" in el.attrib:
            el.set("Value", "0")
        if el.tag == "DefaultDuration" and "Value" in el.attrib:
            el.set("Value", "44100")
        if el.tag == "DefaultSampleRate" and "Value" in el.attrib:
            el.set("Value", "44100")

    for clip in at.iter("AudioClip"):
        n = clip.find("Name")
        if n is not None:
            n.set("Value", "PLACEHOLDER")
        w = clip.find("IsWarped")
        if w is not None:
            w.set("Value", "true")
        ce = clip.find("CurrentEnd")
        if ce is not None:
            ce.set("Value", "16")
        loop = clip.find("Loop")
        if loop is not None:
            le = loop.find("LoopEnd")
            if le is not None:
                le.set("Value", "16")

    for name in at.findall("Name"):
        for child in name:
            if child.tag in ("EffectiveName", "UserName", "MemorizedFirstClipName"):
                child.set("Value", "Track")

    for t in list(tracks):
        tracks.remove(t)
    tracks.append(at)
    if returns:
        tracks.append(returns[0])

    for tempo in ls.iter("Tempo"):
        man = tempo.find("Manual")
        if man is not None:
            man.set("Value", "140")

    scenes = ls.find("Scenes")
    if scenes is not None:
        for s in list(scenes)[8:]:
            scenes.remove(s)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    xml_str = ET.tostring(root, encoding="unicode")
    if not xml_str.startswith("<?xml"):
        xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str
    OUT.write_text(xml_str, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    main(src)
