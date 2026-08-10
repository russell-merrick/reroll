"""
Automated Serum ↔ kick-grid sync test (no listening required).

Renders a quarter-note pattern through Serum and checks:
  1) First onset is near t=0 (kick downbeat)
  2) Inter-onset intervals match one beat @ BPM (not 1.0s — the old bug)

Run:
  py -3.12 host/test_serum_sync.py

Exit 0 = pass. Exit 1 = fail.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from host.renderer import grid_to_notes, render_midi  # noqa: E402

BPM = 140.0
BARS = 2
# Spacing must match beat length (old bug put notes 1.0s apart)
IOI_THRESH_MS = 25.0
FIRST_ONSET_THRESH_MS = 20.0


def _find_preset() -> Path | None:
    home = Path.home()
    candidates = [
        home / "Documents/Xfer/Serum 2 Presets/Presets/Factory/Bass/Hard",
        home / "Documents/Xfer/Serum 2 Presets/Presets/Splice",
        home / "Documents/Xfer/Serum Presets/Presets/Bass",
        home / "Documents/Xfer/Serum Presets/Presets/Splice",
    ]
    for folder in candidates:
        if not folder.is_dir():
            continue
        for ext in ("*.SerumPreset", "*.fxp"):
            found = list(folder.rglob(ext))
            if found:
                return found[0]
    return None


def energy_onsets_sec(wav_path: Path, *, thr_frac: float = 0.18) -> list[float]:
    sr, pcm = wavfile.read(str(wav_path))
    mono = pcm.astype(np.float64)
    if mono.ndim == 2:
        mono = mono.mean(axis=1)
    mono = np.abs(mono)
    hop = max(1, int(sr * 0.005))
    rms = np.array(
        [np.sqrt(np.mean(mono[i : i + hop] ** 2)) for i in range(0, len(mono) - hop, hop)]
    )
    if not rms.size or float(rms.max()) < 1e-9:
        return []
    thr = thr_frac * float(rms.max())
    starts: list[float] = []
    on = False
    for i, v in enumerate(rms):
        if not on and v >= thr:
            starts.append(i * hop / float(sr))
            on = True
        elif on and v < thr * 0.2:
            on = False
    return starts


def main() -> int:
    preset = _find_preset()
    if not preset:
        print("SKIP: no Serum preset found under Documents/Xfer")
        return 0

    grid: list[dict | None] = [None] * 16
    for s in (0, 4, 8, 12):
        grid[s] = {"degree": 0, "length": 1, "vel": 127}

    notes = grid_to_notes(grid, key="F minor", octave=3, bars=BARS)
    print(f"preset: {preset}")
    print(f"notes: {len(notes)} @ {BPM} BPM × {BARS} bars")

    result = render_midi(
        notes,
        bpm=BPM,
        bars=BARS,
        fxp_path=preset,
        use_cache=False,
    )
    if not result.get("ok"):
        print(f"FAIL: render error: {result.get('error')}")
        return 1

    starts = energy_onsets_sec(Path(result["wav"]))
    beat_sec = 60.0 / BPM
    expected_ioi = beat_sec

    print(f"latency_samples:     {result.get('latency_samples')}")
    print(f"onset_shift_samples: {result.get('onset_shift_samples')}")
    print(f"detected_onsets_s:   {[round(s, 3) for s in starts[:8]]}")
    print(f"expected_beats_s:    {[round(i * beat_sec, 3) for i in range(8)]}")

    if len(starts) < 4:
        print(f"FAIL: only {len(starts)} onsets detected (need ≥4)")
        return 1

    first_ms = 1000.0 * starts[0]
    print(f"first_onset_ms:      {first_ms:+.2f}")
    if abs(first_ms) > FIRST_ONSET_THRESH_MS:
        print(f"FAIL: first onset {first_ms:.1f} ms from 0 (kick downbeat)")
        return 1

    iois = np.diff(starts[:8])
    ioi_err_ms = 1000.0 * (iois - expected_ioi)
    mean_ioi_err = float(np.mean(np.abs(ioi_err_ms)))
    max_ioi_err = float(np.max(np.abs(ioi_err_ms)))
    print(f"IOI mean|err| ms:    {mean_ioi_err:.2f}  (want ~0; beat={beat_sec*1000:.1f}ms)")
    print(f"IOI max|err| ms:     {max_ioi_err:.2f}")
    print(f"IOI errors ms:       {[round(float(x), 1) for x in ioi_err_ms]}")

    # The historical bug placed notes 1.0s apart → ~571ms IOI error @ 140BPM
    if max_ioi_err > IOI_THRESH_MS:
        print(
            f"FAIL: note spacing off by up to {max_ioi_err:.1f} ms "
            f"(DawDreamer MIDI must use beats=True)"
        )
        return 1

    print(
        f"PASS: first onset within ±{FIRST_ONSET_THRESH_MS} ms; "
        f"IOI within ±{IOI_THRESH_MS} ms of one beat"
    )
    return 0


if __name__ == "__main__":
    code = main()
    # Serum/DawDreamer often ACCESS_VIOLATIONs on interpreter teardown after a pass.
    import os

    os._exit(code)
