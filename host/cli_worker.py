"""
Long-lived Serum host worker (Python 3.12).

Keeps DawDreamer + Serum warm between jobs so MIDI/dice/BPM updates don't
pay process-start + plugin-load every time.

Protocol: one JSON object per line on stdin → one JSON object per line on stdout.

  {"id": 1, "action": "render", "bpm": 140, "bars": 4, "fxp": "...", "grid": [...], ...}
  {"id": 2, "action": "macros", "fxp": "..."}
  {"id": 3, "action": "ping"}
  {"id": 4, "action": "shutdown"}

Run:
  py -3.12 host/cli_worker.py
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from host.renderer import (  # noqa: E402
    SerumSession,
    grid_to_notes,
)


def _reply(msg: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    session = SerumSession()
    _reply({"ok": True, "event": "ready", "pid": __import__("os").getpid()})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req_id = None
        try:
            req = json.loads(line)
            if not isinstance(req, dict):
                _reply({"ok": False, "error": "request must be object"})
                continue
            req_id = req.get("id")
            action = (req.get("action") or "render").lower()

            if action in ("shutdown", "quit", "exit"):
                _reply({"ok": True, "id": req_id, "event": "bye"})
                return 0

            if action == "ping":
                _reply({"ok": True, "id": req_id, "event": "pong", "warm": session.summary()})
                continue

            if action == "macros":
                result = session.inspect_macros(
                    req.get("fxp"), plugin_path=req.get("plugin")
                )
                result["id"] = req_id
                _reply(result)
                continue

            # render
            notes = req.get("notes")
            if notes is None and req.get("grid") is not None:
                notes = grid_to_notes(
                    req["grid"],
                    key=req.get("key", "F minor"),
                    octave=int(req.get("octave", 2)),
                    bars=int(req.get("bars", 4)),
                )
            if not notes:
                _reply({"ok": False, "id": req_id, "error": "no notes"})
                continue

            macros = req.get("macros")
            if macros is not None and not isinstance(macros, list):
                macros = None

            result = session.render_midi(
                notes,
                bpm=float(req.get("bpm", 140)),
                bars=int(req.get("bars", 4)),
                fxp_path=req.get("fxp"),
                plugin_path=req.get("plugin"),
                out_path=req.get("out"),
                use_cache=bool(req.get("use_cache", True)),
                macros=macros,
            )
            result["id"] = req_id
            _reply(result)

        except Exception as exc:
            _reply(
                {
                    "ok": False,
                    "id": req_id,
                    "error": str(exc),
                    "trace": traceback.format_exc()[-1500:],
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
