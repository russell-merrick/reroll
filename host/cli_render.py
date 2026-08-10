"""
CLI entry for Serum render (run with Python 3.12).

  py -3.12 host/cli_render.py --request request.json --out out.wav

Serum 2 often ACCESS_VIOLATIONs on process teardown. Always write result JSON
to result_path (and stdout) before exit so the backend can read success even
when the process dies uncleanly.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# allow `py -3.12 host/cli_render.py` from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from host.renderer import grid_to_notes, inspect_macros, render_midi  # noqa: E402


def _emit(result: dict, result_path: str | None) -> None:
    """Persist + print JSON, then hard-exit on success to skip VST teardown crash."""
    text = json.dumps(result)
    if result_path:
        try:
            Path(result_path).write_text(text, encoding="utf-8")
        except OSError:
            pass
    try:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
    except OSError:
        pass
    # Avoid DawDreamer/Serum2 destructor ACCESS_VIOLATION after successful work
    if result.get("ok"):
        os._exit(0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", required=True, help="JSON request path")
    ap.add_argument("--out", default="", help="Optional explicit wav path")
    args = ap.parse_args()

    req = json.loads(Path(args.request).read_text(encoding="utf-8-sig"))
    result_path = req.get("result_path") or None

    # Inspect MACRO 1–8 defaults from a preset (no render)
    if req.get("action") == "macros":
        result = inspect_macros(req.get("fxp"), plugin_path=req.get("plugin"))
        _emit(result, result_path)
        return 0 if result.get("ok") else 1

    notes = req.get("notes")
    if notes is None and req.get("grid") is not None:
        notes = grid_to_notes(
            req["grid"],
            key=req.get("key", "F minor"),
            octave=int(req.get("octave", 2)),
            bars=int(req.get("bars", 4)),
        )
    if not notes:
        _emit({"ok": False, "error": "no notes"}, result_path)
        return 2

    macros = req.get("macros")
    if macros is not None and not isinstance(macros, list):
        macros = None

    result = render_midi(
        notes,
        bpm=float(req.get("bpm", 140)),
        bars=int(req.get("bars", 4)),
        fxp_path=req.get("fxp"),
        plugin_path=req.get("plugin"),
        out_path=args.out or req.get("out"),
        use_cache=bool(req.get("use_cache", True)),
        macros=macros,
    )
    _emit(result, result_path)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
