"""Debug NextPointeeId vs max Id in generated ALS."""
from __future__ import annotations

import gzip
import re
import wave
from pathlib import Path
import xml.etree.ElementTree as ET

from backend.export_als import (
    TEMPLATE_PATH,
    _load_template,
    _max_id_in_tree,
    write_als_project,
)

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    root = _load_template(TEMPLATE_PATH)
    ls = root.find("LiveSet")
    npi = ls.find("NextPointeeId") if ls is not None else None
    print("template NextPointeeId", npi.get("Value") if npi is not None else None)
    print("template max Id", _max_id_in_tree(root))
    ids = []
    for el in root.iter():
        if "Id" in el.attrib:
            try:
                ids.append((int(el.attrib["Id"]), el.tag))
            except ValueError:
                pass
    ids.sort(reverse=True)
    print("top template ids:", ids[:15])

    p = ROOT / "exports" / "_npi_debug"
    p.mkdir(parents=True, exist_ok=True)
    wavs = []
    for i in range(5):
        w = p / f"t{i}.wav"
        with wave.open(str(w), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            wf.writeframes(b"\x00\x10" * 2000)
        wavs.append({"name": w.name, "abs_path": w, "track": f"t{i}"})

    out = write_als_project(
        parent_dir=p / "out",
        project_name="NPI Debug",
        bpm=140,
        bars=4,
        audio_files=wavs,
    )
    print("out ok", out.get("ok"), out.get("als_path"))
    als = Path(out["als_path"])
    xml = gzip.decompress(als.read_bytes()).decode("utf-8")
    root2 = ET.fromstring(xml)
    npi2 = root2.find("LiveSet").find("NextPointeeId")
    print("written NextPointeeId", npi2.get("Value") if npi2 is not None else None)
    print("written max Id", _max_id_in_tree(root2))
    m = re.search(r'NextPointeeId[^>]*Value="(\d+)"', xml)
    print("raw NextPointeeId", m.group(1) if m else None)
    print("15500 in file?", "15500" in xml)
    print("22154 in file?", "22154" in xml)

    ids2 = []
    for el in root2.iter():
        if "Id" in el.attrib:
            try:
                ids2.append((int(el.attrib["Id"]), el.tag))
            except ValueError:
                pass
    ids2.sort(reverse=True)
    print("top written ids:", ids2[:20])

    # Also check Pointee / Value ids Live might count
    for pat in (r'Id="(\d+)"', r'Value="(\d+)"'):
        nums = [int(x) for x in re.findall(pat, xml)]
        print(f"max from {pat}:", max(nums) if nums else None)


if __name__ == "__main__":
    main()
