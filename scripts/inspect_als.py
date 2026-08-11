"""Inspect ALS template / exports for problematic Live classes."""
from __future__ import annotations

import gzip
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_xml(path: Path) -> str:
    data = path.read_bytes()
    if data[:2] == b"\x1f\x8b":
        return gzip.decompress(data).decode("utf-8", "replace")
    return data.decode("utf-8", "replace")


def main() -> None:
    paths = [ROOT / "backend/templates/live_set_template.xml"]
    paths += list((ROOT / "exports").rglob("*.als"))[:15]
    if len(sys.argv) > 1:
        paths = [Path(p) for p in sys.argv[1:]]

    for path in paths:
        if not path.is_file():
            continue
        text = load_xml(path)
        n = text.count("MidiEditorLaneModel")
        creator = re.search(r'Creator="([^"]+)"', text)
        minor = re.search(r'MinorVersion="([^"]+)"', text)
        print(f"\n=== {path} ===")
        print(f"  MidiEditorLaneModel={n} Creator={creator.group(1) if creator else '?'} Minor={minor.group(1) if minor else '?'}")
        if n:
            idx = text.find("MidiEditorLaneModel")
            print("  context:", text[max(0, idx - 120) : idx + 200].replace("\n", " "))
        # other live12-ish tags
        for tag in (
            "MidiEditorLaneModel",
            "ContentLanes",
            "ExpressionLanes",
            "InstrumentMeld",
            "Roar",
            "MxPatchRef",
            "AudioOut/Main",
        ):
            c = text.count(tag)
            if c:
                print(f"  {tag}: {c}")


if __name__ == "__main__":
    main()
