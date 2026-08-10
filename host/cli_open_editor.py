"""
Open Serum's full plugin UI (not a true standalone — Xfer ships plugin-only).

  py -3.12 host/cli_open_editor.py --fxp "C:\\...\\preset.fxp"

Blocks until the editor window is closed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from host.renderer import load_preset, pick_plugin  # noqa: E402

SAMPLE_RATE = 44100
BUFFER = 128


def main() -> int:
    ap = argparse.ArgumentParser(description="Open Serum 1/2 plugin editor UI")
    ap.add_argument("--fxp", default="", help="Optional .fxp or .SerumPreset to load first")
    ap.add_argument("--plugin", default="", help="Optional Serum DLL/VST path")
    args = ap.parse_args()

    import dawdreamer as daw

    fxp = args.fxp.strip() or None
    try:
        plugin = (
            Path(args.plugin)
            if args.plugin
            else pick_plugin(prefer_fxp=True, preset_path=fxp)
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if not Path(plugin).exists():
        print(f"plugin not found: {plugin}", file=sys.stderr)
        return 2

    engine = daw.RenderEngine(SAMPLE_RATE, BUFFER)
    synth = engine.make_plugin_processor("serum", str(plugin))

    if fxp:
        ok = load_preset(synth, fxp)
        print(f"preset_loaded={ok} path={fxp}")
    else:
        print("preset_loaded=false (no preset)")

    print(f"opening editor · {plugin}")
    try:
        synth.open_editor()
    except Exception as exc:
        print(f"open_editor failed: {exc}", file=sys.stderr)
        return 1
    print("editor closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
