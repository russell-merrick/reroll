"""Strip Live-12-only nodes from live_set_template.xml so Live 11+ can open it."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TPL = ROOT / "backend" / "templates" / "live_set_template.xml"

# Whole subtrees Live 11 (and some Live 12 builds) reject as "unknown class"
DROP_TAGS = {
    "ExpressionLanes",
    "ContentLanes",
    "MidiEditorLaneModel",
    "InstrumentMeld",
    "Roar",
    "MxPatchRef",
    "DetailClipKeyMidis",
}


def strip_tree(root: ET.Element) -> int:
    removed = 0
    for parent in list(root.iter()):
        kids = list(parent)
        for child in kids:
            if child.tag in DROP_TAGS:
                parent.remove(child)
                removed += 1
    # Recursive second pass for nested leftovers
    again = True
    while again:
        again = False
        for parent in list(root.iter()):
            for child in list(parent):
                if child.tag in DROP_TAGS:
                    parent.remove(child)
                    removed += 1
                    again = True
    return removed


def main() -> None:
    text = TPL.read_text(encoding="utf-8")
    # Live 12 renamed Master → Main; older Live wants Master
    text = text.replace("AudioOut/Main", "AudioOut/Master")
    root = ET.fromstring(text)
    n = strip_tree(root)

    # Honest Live 11 header (content is sanitized for it)
    root.set("MajorVersion", "5")
    root.set("MinorVersion", "11.0_11300")
    root.set("SchemaChangeCount", "3")
    root.set("Creator", "Ableton Live 11.3.21")
    root.set("Revision", "reroll-export-template")

    out = ET.tostring(root, encoding="unicode")
    if not out.startswith("<?xml"):
        out = '<?xml version="1.0" encoding="UTF-8"?>\n' + out
    TPL.write_text(out, encoding="utf-8")
    print(f"sanitized {TPL} removed_subtrees≈{n} size={TPL.stat().st_size}")
    # verify
    check = TPL.read_text(encoding="utf-8")
    for bad in ("MidiEditorLaneModel", "ExpressionLanes", "ContentLanes", "AudioOut/Main"):
        print(f"  {bad}: {check.count(bad)}")


if __name__ == "__main__":
    main()
