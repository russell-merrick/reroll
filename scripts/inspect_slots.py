"""Inspect all ClipSlotList / Scenes counts in newest real .als export."""
from __future__ import annotations

import gzip
import re
import sys
from pathlib import Path
import xml.etree.ElementTree as ET


def main() -> None:
    if len(sys.argv) > 1:
        als = Path(sys.argv[1])
    else:
        cands = [
            p
            for p in Path("exports").rglob("*.als")
            if not any(part.startswith("_") for part in p.parts)
        ]
        als = sorted(cands, key=lambda p: p.stat().st_mtime, reverse=True)[0]

    print("FILE", als)
    xml = gzip.decompress(als.read_bytes()).decode("utf-8")
    root = ET.fromstring(xml)
    ls = root.find("LiveSet")
    scenes = ls.find("Scenes") if ls is not None else None
    print("Scenes", len(list(scenes)) if scenes is not None else None)

    parent_of: dict[ET.Element, ET.Element] = {}
    for parent in root.iter():
        for child in parent:
            parent_of[child] = parent

    for csl in root.iter("ClipSlotList"):
        parent = parent_of.get(csl)
        gp = parent_of.get(parent) if parent is not None else None
        n = sum(1 for s in csl if s.tag == "ClipSlot")
        filled = sum(1 for s in csl if any(True for _ in s.iter("AudioClip")))
        print(
            f"ClipSlotList parent={getattr(parent, 'tag', None)} "
            f"gp={getattr(gp, 'tag', None)} slots={n} filled={filled}"
        )

    for tag in ("MainTrack", "PreHearTrack", "ReturnTrack", "AudioTrack", "MidiTrack"):
        for t in root.iter(tag):
            lists = []
            for csl in t.iter("ClipSlotList"):
                lists.append(sum(1 for s in csl if s.tag == "ClipSlot"))
            if lists:
                print(tag, "Id", t.get("Id"), "slotlists", lists)

    m = re.search(r'NextPointeeId[^>]*Value="(\d+)"', xml)
    print("NextPointeeId", m.group(1) if m else None)
    print("ReturnTrack", sum(1 for _ in root.iter("ReturnTrack")))
    print("TrackSendHolder", sum(1 for _ in root.iter("TrackSendHolder")))
    # any other *Slot* lists
    tags = sorted({el.tag for el in root.iter() if "Slot" in el.tag or "Scene" in el.tag})
    print("Slot/Scene tags", tags)
    for tag in tags:
        print(f"  count {tag}: {sum(1 for _ in root.iter(tag))}")


if __name__ == "__main__":
    main()
