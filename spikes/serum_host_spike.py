"""
Spike: load Serum 2 via DawDreamer (Python 3.12) and render MIDI → WAV.

  py -3.12 -m pip install dawdreamer numpy scipy
  py -3.12 spikes/serum_host_spike.py

Success = spikes/out/serum_spike.wav with non-trivial peak level.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

SAMPLE_RATE = 44100
BUFFER = 128
OUT_DIR = Path(__file__).resolve().parent / "out"

SERUM2_BUNDLE = Path(r"C:\Program Files\Common Files\VST3\Serum2.vst3")
SERUM2_BIN = Path(
    r"C:\Program Files\Common Files\VST3\Serum2.vst3\Contents\x86_64-win\Serum2.vst3"
)
SERUM1_BIN = Path(
    r"C:\Program Files\Common Files\VST3\Serum.vst3\Contents\x86_64-win\Serum.vst3"
)


def try_dawdreamer(plugin_path: Path) -> dict:
    result: dict = {"backend": "dawdreamer", "path": str(plugin_path)}
    try:
        import dawdreamer as daw
        import numpy as np
    except ImportError as e:
        result["ok"] = False
        result["error"] = (
            f"import failed — use Python 3.12: py -3.12 -m pip install dawdreamer ({e})"
        )
        return result

    try:
        print(f"[dawdreamer] loading {plugin_path} ...")
        engine = daw.RenderEngine(SAMPLE_RATE, BUFFER)
        synth = engine.make_plugin_processor("serum", str(plugin_path))
        result["ok"] = True
        result["name"] = synth.get_name() if hasattr(synth, "get_name") else "serum"

        # 1 bar @ 140 BPM: C2 quarters
        bpm = 140.0
        if hasattr(synth, "add_midi_note"):
            for i in range(4):
                synth.add_midi_note(36, 100, float(i), 0.9)
            result["midi_api"] = "add_midi_note"
        else:
            result["midi_api"] = "missing"
            result["dir"] = [x for x in dir(synth) if not x.startswith("_")][:40]

        duration = (60.0 / bpm) * 4.0
        engine.load_graph([(synth, [])])
        engine.render(duration)
        audio = engine.get_audio()
        peak = float(np.max(np.abs(audio))) if audio is not None else 0.0
        result["render_peak"] = peak
        result["render_shape"] = list(audio.shape) if hasattr(audio, "shape") else None
        result["success_audio"] = peak > 1e-4

        if peak > 1e-6:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            try:
                from scipy.io import wavfile

                pcm = (np.clip(audio.T, -1, 1) * 32767).astype(np.int16)
                out_path = OUT_DIR / "serum_spike.wav"
                wavfile.write(str(out_path), SAMPLE_RATE, pcm)
                result["wav"] = str(out_path)
            except Exception as e:
                result["wav_error"] = str(e)

    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()
    return result


def try_pedalboard_load(plugin_bin: Path, plugin_name: str | None = None) -> dict:
    result: dict = {
        "backend": "pedalboard",
        "path": str(plugin_bin),
        "plugin_name": plugin_name,
    }
    try:
        from pedalboard import load_plugin
    except ImportError as e:
        result["ok"] = False
        result["error"] = f"import failed: {e}"
        return result

    try:
        kwargs = {}
        if plugin_name:
            kwargs["plugin_name"] = plugin_name
        print(f"[pedalboard] loading {plugin_bin} name={plugin_name!r} ...")
        pl = load_plugin(str(plugin_bin), **kwargs)
        result["ok"] = True
        result["name"] = getattr(pl, "name", None)
        result["is_instrument"] = getattr(pl, "is_instrument", None)
        result["note"] = "Loads instrument; MIDI→audio not implemented in this spike"
    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)
    return result


def main() -> int:
    print("Python", sys.version)
    print("Serum2 bundle:", SERUM2_BUNDLE.exists(), SERUM2_BUNDLE)
    print("Serum2 bin:", SERUM2_BIN.exists())
    print("Serum1 bin:", SERUM1_BIN.exists())

    results = []

    # DawDreamer prefers the .vst3 bundle path
    plugin = SERUM2_BUNDLE if SERUM2_BUNDLE.exists() else SERUM1_BIN
    print("\n=== dawdreamer (primary) ===")
    r = try_dawdreamer(plugin)
    results.append(r)
    for k, v in r.items():
        print(f"  {k}: {v}")

    print("\n=== pedalboard load-only (optional) ===")
    if SERUM2_BIN.exists():
        r2 = try_pedalboard_load(SERUM2_BIN, "Serum 2")
        results.append(r2)
        for k, v in r2.items():
            print(f"  {k}: {v}")
    if SERUM1_BIN.exists():
        r3 = try_pedalboard_load(SERUM1_BIN)
        results.append(r3)
        for k, v in r3.items():
            print(f"  {k}: {v}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = OUT_DIR / "spike_report.txt"
    lines = [f"Python {sys.version}", ""]
    for r in results:
        lines.append(f"--- {r.get('backend')} ---")
        for k, v in r.items():
            lines.append(f"{k}: {v}")
        lines.append("")
    report.write_text("\n".join(lines), encoding="utf-8")
    print("\nWrote", report)

    audio_ok = any(r.get("success_audio") for r in results)
    if audio_ok:
        print("\nSUCCESS: Serum produced audio via DawDreamer.")
        return 0
    print("\nFAIL: no audible render.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
