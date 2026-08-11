"""
Offline render of a sample track into a full session loop stem (WAV).

Mirrors frontend scheduling:
  - one-shots placed on PATTERNS[type] every bar for `bars`
  - phrase/loop samples stretched/looped to fill the cycle
"""

from __future__ import annotations

import re
import wave
from pathlib import Path
from typing import Any

import numpy as np

from .timing import LOOP_BARS, cycle_sec, sec_per_16th

# Match frontend app.js PATTERNS / SLOT_GAIN (1 bar of 16ths, repeated)
PATTERNS: dict[str, list[int]] = {
    "kick": [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0],
    "clap": [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
    "snare": [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
    "hats": [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 1],
    "perc": [0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1, 0],
    "fx": [0] * 16,
    "lead_audio": [1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0],
    "vocal": [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
}

SLOT_GAIN: dict[str, float] = {
    "kick": 1.0,
    "clap": 0.85,
    "snare": 0.85,
    "hats": 0.45,
    "perc": 0.55,
    "fx": 0.5,
    "vocal": 0.55,
    "lead_audio": 0.55,
    "loop": 0.6,
}

TARGET_SR = 44100


def parse_bpm_from_name(name: str) -> float | None:
    s = str(name or "")
    m = re.search(r"(?:^|[_\-\s.])(\d{2,3})\s*bpm\b", s, re.I) or re.search(
        r"\bbpm[_\-\s.]*(\d{2,3})\b", s, re.I
    )
    if m:
        n = int(m.group(1))
        if 60 <= n <= 200:
            return float(n)
    for m in re.finditer(r"(?:^|[_\-\s./\\])(\d{2,3})(?=[_\-\s./\\]|$)", s):
        n = int(m.group(1))
        if 70 <= n <= 200:
            return float(n)
    return None


def is_phrase_sample(
    duration_sec: float,
    name: str = "",
    track_type: str = "",
    *,
    bpm: float = 140,
) -> bool:
    """Mirror frontend isPhraseSample (approx)."""
    n = str(name).lower()
    t = str(track_type or "").lower()
    # Avoid matching project paths like "loop_gen_project" (loop_ prefix false positive)
    if re.search(
        r"(?:^|[^a-z0-9])loops?(?:[^a-z0-9]|$)|_loops?(?:[^a-z0-9]|$)|"
        r"looper|looped|phrase|screech|top[_-]?loop|full[_-]?loop|"
        r"drum[_-]?loop|hat[_-]?loop|perc[_-]?loop|melody|melodic|"
        r"atmosphere|ambient|texture|(?:^|[^a-z0-9])bed(?:[^a-z0-9]|$)|"
        r"groove|construction|(?:^|[^a-z0-9])stem(?:[^a-z0-9]|$)|"
        r"(?:^|[^a-z0-9])fill(?:[^a-z0-9]|$)",
        n,
    ):
        return True
    if re.search(r"\brolling\b", n) and duration_sec > 0.8:
        return True
    if parse_bpm_from_name(name) and duration_sec > 0.9:
        return True
    bar_sec = sec_per_16th(bpm) * 16
    is_drum = t in ("kick", "clap", "snare", "hats", "perc")
    if is_drum:
        if t in ("hats", "perc") and duration_sec >= bar_sec * 0.55:
            return True
        return duration_sec >= bar_sec * 1.4
    return duration_sec > max(1.0, bar_sec * 0.55)


def _read_wav(path: Path) -> tuple[np.ndarray, int]:
    """
    Load audio as float32 shape (n_samples, channels), sample rate.
    Prefer scipy for 24-bit; fall back to wave module.
    """
    path = Path(path)
    try:
        from scipy.io import wavfile

        sr, data = wavfile.read(str(path))
        if data.dtype == np.int16:
            audio = data.astype(np.float32) / 32768.0
        elif data.dtype == np.int32:
            audio = data.astype(np.float32) / 2147483648.0
        elif data.dtype == np.uint8:
            audio = (data.astype(np.float32) - 128.0) / 128.0
        else:
            audio = np.asarray(data, dtype=np.float32)
            peak = float(np.max(np.abs(audio))) if audio.size else 1.0
            if peak > 1.5:
                audio = audio / max(peak, 1.0)
        if audio.ndim == 1:
            audio = audio[:, np.newaxis]
        return audio, int(sr)
    except Exception:
        pass

    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        nch = wf.getnchannels()
        sw = wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())
    if sw == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 3:
        # 24-bit little-endian packed
        a = np.frombuffer(raw, dtype=np.uint8).astype(np.int32)
        b = a[0::3] | (a[1::3] << 8) | (a[2::3] << 16)
        b = np.where(b >= 0x800000, b - 0x1000000, b)
        data = b.astype(np.float32) / 8388608.0
    elif sw == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        data = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
        data = (data - 128.0) / 128.0
    if nch > 1:
        data = data.reshape(-1, nch)
    else:
        data = data.reshape(-1, 1)
    return data, int(sr)


def _write_wav(path: Path, audio: np.ndarray, sr: int = TARGET_SR) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if audio.ndim == 1:
        audio = audio[:, np.newaxis]
    # peak soft-limit
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 1.0:
        audio = audio / peak * 0.99
    pcm = np.clip(audio, -1.0, 1.0)
    pcm_i16 = (pcm * 32767.0).astype(np.int16)
    nch = pcm_i16.shape[1]
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(nch)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm_i16.tobytes())


def _resample(audio: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out or audio.size == 0:
        return audio
    n_in = audio.shape[0]
    n_out = max(1, int(round(n_in * sr_out / sr_in)))
    x_old = np.linspace(0.0, 1.0, n_in, endpoint=False)
    x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
    channels = []
    for c in range(audio.shape[1]):
        channels.append(np.interp(x_new, x_old, audio[:, c]).astype(np.float32))
    return np.stack(channels, axis=1)


def _time_stretch(audio: np.ndarray, rate: float) -> np.ndarray:
    """Cheap resample stretch (rate > 1 = faster/shorter)."""
    rate = float(rate)
    if not np.isfinite(rate) or abs(rate - 1.0) < 1e-4 or audio.size == 0:
        return audio
    rate = max(0.25, min(4.0, rate))
    n_in = audio.shape[0]
    n_out = max(1, int(round(n_in / rate)))
    x_old = np.linspace(0.0, 1.0, n_in, endpoint=False)
    x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
    channels = [
        np.interp(x_new, x_old, audio[:, c]).astype(np.float32)
        for c in range(audio.shape[1])
    ]
    return np.stack(channels, axis=1)


def _mix_at(out: np.ndarray, hit: np.ndarray, start: int, gain: float = 1.0) -> None:
    if hit.size == 0 or start >= out.shape[0]:
        return
    # Channel match
    if hit.shape[1] != out.shape[1]:
        if hit.shape[1] == 1 and out.shape[1] == 2:
            hit = np.repeat(hit, 2, axis=1)
        elif hit.shape[1] == 2 and out.shape[1] == 1:
            hit = hit.mean(axis=1, keepdims=True)
        else:
            hit = hit[:, : out.shape[1]]
    end = min(out.shape[0], start + hit.shape[0])
    n = end - start
    if n <= 0:
        return
    out[start:end] += hit[:n] * float(gain)


def _phrase_rate(duration_sec: float, name: str, bpm: float, bars: int) -> float:
    native = parse_bpm_from_name(name)
    if native:
        return max(0.25, min(4.0, float(bpm) / native))
    if duration_sec <= 0.05:
        return 1.0
    bar_sec = sec_per_16th(bpm) * 16
    n_bars = int(round(duration_sec / bar_sec)) if bar_sec > 0 else 1
    n_bars = max(1, min(int(bars), n_bars if n_bars >= 1 else 1))
    target = n_bars * bar_sec
    return max(0.25, min(4.0, duration_sec / target)) if target > 0 else 1.0


def render_sample_loop(
    sample_path: Path | str,
    dest_path: Path | str,
    *,
    track_type: str = "kick",
    bpm: float = 140,
    bars: int = LOOP_BARS,
    name_blob: str | None = None,
) -> dict[str, Any]:
    """
    Render one sample track as a full-loop stereo/mono WAV at TARGET_SR.

    Returns dict with ok, path, duration_sec, mode (pattern|phrase|once), error?
    """
    src = Path(sample_path)
    dest = Path(dest_path)
    ttype = str(track_type or "kick").split("__")[0].lower()
    # Filename / display only — full paths can false-positive phrase rules (e.g. loop_gen_*)
    blob = name_blob if name_blob is not None else src.name
    bars = max(1, min(32, int(bars or LOOP_BARS)))
    bpm = float(bpm or 140)

    if not src.is_file():
        return {"ok": False, "error": f"missing sample: {src}"}

    try:
        audio, sr = _read_wav(src)
    except Exception as exc:
        return {"ok": False, "error": f"read failed: {exc}"}

    audio = _resample(audio, sr, TARGET_SR)
    if audio.shape[1] > 2:
        audio = audio[:, :2]
    dur = audio.shape[0] / float(TARGET_SR)
    total_sec = cycle_sec(bpm, bars)
    n_out = max(1, int(round(total_sec * TARGET_SR)))
    n_ch = audio.shape[1]
    out = np.zeros((n_out, n_ch), dtype=np.float32)

    phrase = is_phrase_sample(dur, blob, ttype, bpm=bpm)
    gain = float(SLOT_GAIN.get(ttype, 0.7))
    mode = "pattern"

    if phrase:
        mode = "phrase"
        rate = _phrase_rate(dur, blob, bpm, bars)
        bed = _time_stretch(audio, rate)
        # Loop-fill the full cycle
        if bed.shape[0] == 0:
            return {"ok": False, "error": "empty audio after stretch"}
        pos = 0
        while pos < n_out:
            _mix_at(out, bed, pos, gain)
            pos += bed.shape[0]
    else:
        pat = PATTERNS.get(ttype)
        sp = sec_per_16th(bpm)
        native = parse_bpm_from_name(blob)
        rate = max(0.25, min(4.0, bpm / native)) if native else 1.0
        hit = _time_stretch(audio, rate) if rate != 1.0 else audio

        if ttype in ("fx", "vocal"):
            mode = "once"
            _mix_at(out, hit, 0, gain)
        elif pat:
            mode = "pattern"
            total_steps = bars * 16
            for step in range(total_steps):
                step_in_bar = step % 16
                if not pat[step_in_bar]:
                    continue
                g = gain
                if ttype == "hats" and step_in_bar % 2 == 1:
                    g *= 0.65
                start = int(round(step * sp * TARGET_SR))
                _mix_at(out, hit, start, g)
        else:
            # Unknown type: fire once at start of each bar? once per cycle like frontend
            mode = "once"
            _mix_at(out, hit, 0, gain)

    try:
        _write_wav(dest, out, TARGET_SR)
    except Exception as exc:
        return {"ok": False, "error": f"write failed: {exc}"}

    return {
        "ok": True,
        "path": str(dest.resolve()),
        "duration_sec": n_out / float(TARGET_SR),
        "mode": mode,
        "bars": bars,
        "bpm": bpm,
        "sample_rate": TARGET_SR,
    }
