"""Inspect an .als for send/return structure Live complains about."""
from __future__ import annotations

import gzip
import re
import sys
from pathlib import Path
import xml.etree.ElementTree as ET


def load(path: Path) -> str:
    data = path.read_bytes()
    if data[:2] == b"\x1f\x8b":
        return gzip.decompress(data).decode("utf-8", "replace")
    return data.decode("utf-8", "replace")


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if path is None:
        cands = sorted(
            Path("exports").rglob("*.als"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        path = next(p for p in cands if not any(part.startswith("_") for part in p.parts))
    print("FILE", path)
    xml = load(path)
    root = ET.fromstring(xml)
    for tag in (
        "ReturnTrack",
        "TrackSendHolder",
        "SendPreBool",
        "Send",
        "Sends",
        "SendsPre",
        "AudioTrack",
        "MidiTrack",
    ):
        print(f"  count {tag}: {sum(1 for _ in root.iter(tag))}")

    tracks = root.find("LiveSet").find("Tracks")
    print("  Tracks children:", [t.tag for t in list(tracks)])
    for t in tracks:
        holders = list(t.iter("TrackSendHolder"))
        sends_elems = list(t.iter("Sends"))
        print(f"  {t.tag} Id={t.get('Id')} holders={len(holders)} Sends_nodes={len(sends_elems)}")
        for s in sends_elems:
            print("    Sends children:", [c.tag for c in list(s)])

    # raw string hits
    for pat in (
        "ReturnTrack",
        "TrackSendHolder",
        "SendPreBool",
        "SendsPre",
        "SessionSends",
        "SessionReturns",
        "ArrangerMixerSends",
        "ArrangerMixerReturns",
    ):
        print(f"  raw '{pat}': {xml.count(pat)}")

    # NextPointeeId
    m = re.search(r'NextPointeeId[^>]*Value="(\d+)"', xml)
    print("  NextPointeeId", m.group(1) if m else None)

    # Size of file
    print("  bytes", path.stat().st_size, "xml_chars", len(xml))


if __name__ == "__main__":
    main()
