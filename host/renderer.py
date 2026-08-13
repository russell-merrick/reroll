"""
Serum offline renderer (Python 3.12 + DawDreamer).

Serum 1 (.fxp):
  C:\\Program Files\\Common Files\\VST3\\Serum_x64.dll  → load_preset()

Serum 2 (.SerumPreset):
  C:\\Program Files\\Common Files\\VST3\\Serum2.vst3
  → serum2-preset-loader convert → load_state()
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Literal

import numpy as np

from backend.midi_util import collapse_tiled_bar_notes

SAMPLE_RATE = 44100
# Offline block size. 128 is a realtime default and makes a 4-bar bounce
# (~7.5s @ 128) do ~2.5k process() calls. 2048 is still well under typical
# Serum latency compensation. Combined with 1-bar-then-tile for repeating
# MIDI patterns this is the main MIDI-edit latency cut.
BUFFER = 2048

DEFAULT_SERUM_DLL = Path(r"C:\Program Files\Common Files\VST3\Serum_x64.dll")
DEFAULT_SERUM2 = Path(r"C:\Program Files\Common Files\VST3\Serum2.vst3")

CACHE_DIR = Path(__file__).resolve().parent / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Fixed macro param indices (after preset load)
SERUM1_MACRO_INDICES = (218, 219, 220, 221)  # MACRO 1–4
SERUM2_MACRO_INDICES = (440, 441, 442, 443, 444, 445, 446, 447)  # Macro 1–8

EngineKind = Literal["serum1", "serum2"]


def is_serum2_preset(path: str | Path | None) -> bool:
    if not path:
        return False
    return Path(path).suffix.lower() == ".serumpreset"


def engine_for_preset(path: str | Path | None) -> EngineKind:
    return "serum2" if is_serum2_preset(path) else "serum1"


def pick_plugin(
    prefer_fxp: bool = True,
    *,
    preset_path: str | Path | None = None,
    plugin_path: str | Path | None = None,
) -> Path:
    if plugin_path:
        p = Path(plugin_path)
        if p.exists():
            return p
    if is_serum2_preset(preset_path):
        if DEFAULT_SERUM2.exists():
            return DEFAULT_SERUM2
        raise FileNotFoundError("Serum2.vst3 required for .SerumPreset files")
    if prefer_fxp and DEFAULT_SERUM_DLL.is_file():
        return DEFAULT_SERUM_DLL
    if DEFAULT_SERUM2.exists():
        return DEFAULT_SERUM2
    if DEFAULT_SERUM_DLL.is_file():
        return DEFAULT_SERUM_DLL
    raise FileNotFoundError("No Serum plugin found (Serum_x64.dll or Serum2.vst3)")


def macro_indices_for(engine: EngineKind) -> tuple[int, ...]:
    return SERUM2_MACRO_INDICES if engine == "serum2" else SERUM1_MACRO_INDICES


def load_fxp(synth, fxp_path: str | Path | None) -> bool:
    if not fxp_path:
        return False
    p = Path(fxp_path)
    if not p.is_file():
        return False
    try:
        return bool(synth.load_preset(str(p.resolve())))
    except Exception:
        return False


def load_serum2_preset(synth, preset_path: str | Path) -> bool:
    """Convert .SerumPreset → JUCE VST3 state → load_state."""
    p = Path(preset_path)
    if not p.is_file():
        return False
    try:
        from serum2_preset_loader import convert_preset_file
    except ImportError as exc:
        raise RuntimeError(
            "serum2-preset-loader not installed. "
            "Run: py -3.12 -m pip install serum2-preset-loader"
        ) from exc

    try:
        state = convert_preset_file(str(p.resolve()))
    except Exception:
        return False

    # DawDreamer load_state wants a file path
    key = hashlib.sha1(str(p.resolve()).encode("utf-8")).hexdigest()[:16]
    state_path = CACHE_DIR / f"s2state_{key}.bin"
    try:
        state_path.write_bytes(state)
        synth.load_state(str(state_path.resolve()))
        return True
    except Exception:
        return False


def load_preset(synth, preset_path: str | Path | None) -> bool:
    if not preset_path:
        return False
    p = Path(preset_path)
    if not p.is_file():
        return False
    if is_serum2_preset(p):
        return load_serum2_preset(synth, p)
    return load_fxp(synth, p)


def _normalize_macros(
    macros: list[float] | None,
    *,
    n: int = 4,
) -> list[float] | None:
    """Return n floats in 0..1, or None if unused."""
    if macros is None:
        return None
    out: list[float] = []
    for i in range(n):
        if i < len(macros) and macros[i] is not None:
            out.append(max(0.0, min(1.0, float(macros[i]))))
        else:
            out.append(0.0)
    return out


def apply_macros(
    synth,
    macros: list[float] | None,
    *,
    engine: EngineKind = "serum1",
) -> bool:
    """Set macro knobs after preset load. Returns True if any were applied."""
    indices = macro_indices_for(engine)
    vals = _normalize_macros(macros, n=len(indices))
    if vals is None:
        return False
    for idx, val in zip(indices, vals):
        try:
            synth.set_parameter(int(idx), float(val))
        except Exception:
            pass
    return True


def is_generic_macro_label(name: str | None) -> bool:
    """True for stock labels like 'Macro 1' / 'MACRO 3' (not a user rename)."""
    n = (name or "").strip()
    if not n:
        return True
    return bool(re.match(r"^MACRO\s*[1-8]$", n, re.I))


def is_mapped_macro_name(name: str | None, *, engine: EngineKind = "serum1") -> bool:
    """
    Serum 1: hide default MACRO 1–4 labels (unmapped).
    Serum 2: show knobs even with stock labels (S2 host rarely exposes renames).
    Custom names always count as mapped.
    """
    n = (name or "").strip()
    if not n:
        return False
    if is_generic_macro_label(n):
        # Serum 2: still show default Macro N knobs when VST names are stock
        return engine == "serum2"
    return True


def read_serum2_macros_from_preset(preset_path: str | Path | None) -> list[dict[str, Any]]:
    """
    Read Macro0..7 display names (+ optional values) from a .SerumPreset.

    Serum 2 stores custom macro labels in the preset CBOR. VST3
    get_parameter_name() almost always returns generic "Macro N" even after
    load_state — same class of issue as Live not showing S2 macro names.
    """
    if not preset_path or not is_serum2_preset(preset_path):
        return []
    p = Path(preset_path)
    if not p.is_file():
        return []
    try:
        from serum2_preset_loader import unwrap_xferjson
        import cbor2
    except ImportError:
        return []
    try:
        _meta, _ver, cbor_blob = unwrap_xferjson(p.read_bytes())
        obj = cbor2.loads(cbor_blob)
    except Exception:
        return []
    if not isinstance(obj, dict):
        return []

    out: list[dict[str, Any]] = []
    for i in range(8):
        raw = obj.get(f"Macro{i}")
        if raw is None:
            raw = obj.get(f"macro{i}")
        name = ""
        value: float | None = None
        if isinstance(raw, dict):
            name = str(raw.get("name") or "").strip()
            pp = raw.get("plainParams")
            if isinstance(pp, dict) and pp.get("kParamValue") is not None:
                try:
                    raw_v = float(pp["kParamValue"])
                    # Preset stores 0..100; normalize if needed
                    value = raw_v / 100.0 if raw_v > 1.0 + 1e-6 else raw_v
                    value = max(0.0, min(1.0, value))
                except (TypeError, ValueError):
                    value = None
            elif pp == "default":
                value = 0.0
        out.append(
            {
                "slot": i + 1,
                "name": name,
                "value": value,
            }
        )
    return out


def apply_serum2_preset_macro_labels(
    macros: list[dict[str, Any]],
    preset_path: str | Path | None,
) -> list[dict[str, Any]]:
    """Overlay .SerumPreset MacroN.name onto host-reported macro list."""
    file_macros = read_serum2_macros_from_preset(preset_path)
    if not file_macros:
        return macros
    by_slot = {int(m["slot"]): m for m in file_macros}
    out: list[dict[str, Any]] = []
    for m in macros:
        slot = int(m.get("slot") or 0)
        fm = by_slot.get(slot)
        if not fm:
            out.append(m)
            continue
        name = (fm.get("name") or "").strip()
        if not name:
            out.append(m)
            continue
        updated = {**m, "name": name, "mapped": True, "name_source": "preset"}
        # Prefer live plugin value; fall back to preset kParamValue if missing
        if m.get("value") is None and fm.get("value") is not None:
            updated["value"] = fm["value"]
        out.append(updated)
    return out


def read_macros_from_synth(
    synth,
    *,
    engine: EngineKind = "serum1",
    mapped_only: bool = False,
) -> list[dict[str, Any]]:
    """Read macro knobs from a loaded plugin instance."""
    indices = macro_indices_for(engine)
    out: list[dict[str, Any]] = []
    for i, idx in enumerate(indices):
        default_name = f"Macro {i + 1}"
        name = default_name
        value = 0.0
        try:
            name = str(synth.get_parameter_name(idx) or default_name)
        except Exception:
            pass
        try:
            value = float(synth.get_parameter(idx))
        except Exception:
            value = 0.0
        mapped = is_mapped_macro_name(name, engine=engine)
        if mapped_only and not mapped:
            continue
        out.append(
            {
                "index": int(idx),
                "slot": i + 1,
                "name": name if name.strip() else default_name,
                "value": max(0.0, min(1.0, value)),
                "mapped": mapped,
                "engine": engine,
            }
        )
    return out


class _WarmSlot:
    """One warm DawDreamer engine + plugin (Serum 1 *or* Serum 2)."""

    __slots__ = ("eng", "synth", "plugin_path", "fxp_path", "engine_kind", "loads", "renders")

    def __init__(self) -> None:
        self.eng = None
        self.synth = None
        self.plugin_path: str | None = None
        self.fxp_path: str | None = None
        self.engine_kind: EngineKind | None = None
        self.loads: int = 0
        self.renders: int = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "warm": self.synth is not None,
            "plugin": self.plugin_path,
            "fxp": self.fxp_path,
            "engine": self.engine_kind,
            "loads": self.loads,
            "renders": self.renders,
        }

    def drop(self) -> None:
        self.eng = None
        self.synth = None
        self.plugin_path = None
        self.fxp_path = None
        self.engine_kind = None


class SerumSession:
    """
    Warm DawDreamer + Serum for repeated renders.

    Keeps **Serum 1 and Serum 2** loaded in the same worker process so a mixed
    bass/lead stack does not tear down one VST to bounce the other. Reloads a
    preset only when the .fxp / .SerumPreset path changes.
    """

    def __init__(self) -> None:
        self._daw = None
        self._slots: dict[EngineKind, _WarmSlot] = {}
        self.eng = None
        self.synth = None
        self.plugin_path: str | None = None
        self.fxp_path: str | None = None
        self.engine_kind: EngineKind | None = None
        self.loads: int = 0
        self.renders: int = 0

    def _slot(self, kind: EngineKind) -> _WarmSlot:
        slot = self._slots.get(kind)
        if slot is None:
            slot = _WarmSlot()
            self._slots[kind] = slot
        return slot

    def _activate(self, slot: _WarmSlot) -> None:
        self.eng = slot.eng
        self.synth = slot.synth
        self.plugin_path = slot.plugin_path
        self.fxp_path = slot.fxp_path
        self.engine_kind = slot.engine_kind
        self.loads = sum(s.loads for s in self._slots.values())
        self.renders = sum(s.renders for s in self._slots.values())

    def _drop_slot(self, kind: EngineKind | None) -> None:
        if kind is None:
            return
        slot = self._slots.get(kind)
        if slot:
            slot.drop()
        if self.engine_kind == kind:
            self.eng = None
            self.synth = None
            self.plugin_path = None
            self.fxp_path = None
            self.engine_kind = None

    def summary(self) -> dict[str, Any]:
        return {
            "warm": any(s.synth is not None for s in self._slots.values()),
            "plugin": self.plugin_path,
            "fxp": self.fxp_path,
            "engine": self.engine_kind,
            "loads": sum(s.loads for s in self._slots.values()),
            "renders": sum(s.renders for s in self._slots.values()),
            "slots": {k: s.snapshot() for k, s in self._slots.items()},
        }

    def _ensure_daw(self):
        if self._daw is None:
            import dawdreamer as daw

            self._daw = daw
        return self._daw

    def ensure_synth(
        self,
        fxp_path: str | Path | None,
        plugin_path: str | Path | None = None,
    ) -> tuple[bool, str]:
        """Load plugin/preset if needed. Returns (fxp_loaded_this_call, error)."""
        engine_kind = engine_for_preset(fxp_path)
        try:
            plugin = pick_plugin(
                prefer_fxp=engine_kind == "serum1",
                preset_path=fxp_path,
                plugin_path=plugin_path,
            )
        except FileNotFoundError as exc:
            return False, str(exc)

        plugin_s = str(plugin.resolve() if hasattr(plugin, "resolve") else plugin)
        fxp_s = str(Path(fxp_path).resolve()) if fxp_path else None
        daw = self._ensure_daw()
        slot = self._slot(engine_kind)

        # New plugin binary for this engine only — leave the other Serum warm.
        if slot.synth is None or slot.plugin_path != plugin_s:
            slot.eng = daw.RenderEngine(SAMPLE_RATE, BUFFER)
            slot.synth = slot.eng.make_plugin_processor("serum", plugin_s)
            slot.plugin_path = plugin_s
            slot.fxp_path = None
            slot.engine_kind = engine_kind
            slot.loads += 1

        self._activate(slot)

        fxp_loaded = False
        if fxp_s and slot.fxp_path != fxp_s:
            ok = bool(load_preset(slot.synth, fxp_path))
            if not ok:
                # Do NOT mark path as loaded — next call should retry, and we must
                # not cache init/default audio under this preset key.
                return False, f"failed to load preset: {fxp_s}"
            fxp_loaded = True
            slot.fxp_path = fxp_s
            slot.engine_kind = engine_kind
            slot.loads += 1
            self._activate(slot)
        elif fxp_s and slot.fxp_path == fxp_s:
            fxp_loaded = True  # already warm with this preset
        return fxp_loaded, ""

    def inspect_macros(
        self,
        fxp_path: str | Path | None,
        *,
        plugin_path: str | Path | None = None,
    ) -> dict[str, Any]:
        engine = engine_for_preset(fxp_path)
        try:
            loaded, err = self.ensure_synth(fxp_path, plugin_path)
            if err:
                return {
                    "ok": False,
                    "error": err,
                    "macros": [],
                    "all_macros": [],
                    "engine": engine,
                }
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "macros": [],
                "all_macros": [],
                "engine": engine,
            }

        eng = self.engine_kind or engine
        all_macros = read_macros_from_synth(self.synth, engine=eng, mapped_only=False)
        # Serum 2: custom labels live in the .SerumPreset CBOR, not VST3 names
        if eng == "serum2" and fxp_path:
            all_macros = apply_serum2_preset_macro_labels(all_macros, fxp_path)
        macros = [m for m in all_macros if m.get("mapped")]
        return {
            "ok": True,
            "fxp_loaded": loaded,
            "plugin": self.plugin_path,
            "fxp": str(fxp_path or ""),
            "engine": eng,
            "macros": macros,
            "all_macros": all_macros,
            "mapped_count": len(macros),
            "warm": True,
        }

    def render_midi(
        self,
        notes: list[dict[str, Any]],
        *,
        bpm: float = 140.0,
        bars: int = 4,
        fxp_path: str | Path | None = None,
        plugin_path: str | Path | None = None,
        out_path: str | Path | None = None,
        use_cache: bool = True,
        macros: list[float] | None = None,
    ) -> dict[str, Any]:
        import time as _time

        from scipy.io import wavfile

        engine_kind = engine_for_preset(fxp_path)
        try:
            plugin = pick_plugin(
                prefer_fxp=engine_kind == "serum1",
                preset_path=fxp_path,
                plugin_path=plugin_path,
            )
        except FileNotFoundError as exc:
            return {"ok": False, "error": str(exc)}

        n_macros = len(macro_indices_for(engine_kind))
        bars_i = max(1, int(bars))
        collapsed = collapse_tiled_bar_notes(notes, bars_i)
        render_notes = collapsed if collapsed is not None else notes
        render_bars = 1 if collapsed is not None else bars_i
        tile_n = bars_i // render_bars
        duration_sec = (60.0 / float(bpm)) * 4.0 * render_bars
        out_duration_sec = (60.0 / float(bpm)) * 4.0 * bars_i
        macro_vals = _normalize_macros(macros, n=n_macros)
        t0 = _time.perf_counter()

        cache_key = hashlib.sha1(
            json.dumps(
                {
                    # v5: bust caches that may have stored init/default audio after failed loads
                    "v": 5,
                    "plugin": str(plugin),
                    "fxp": str(Path(fxp_path).resolve()) if fxp_path else "",
                    "engine": engine_kind,
                    "bpm": bpm,
                    "bars": bars,
                    "notes": notes,
                    "macros": macro_vals,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:16]
        cache_wav = CACHE_DIR / f"{cache_key}.wav"
        if use_cache and cache_wav.is_file():
            return {
                "ok": True,
                "cached": True,
                "wav": str(cache_wav),
                "peak": None,
                "fxp_loaded": None,
                "plugin": str(plugin),
                "engine": engine_kind,
                "macros": macro_vals,
                "warm": self.synth is not None,
                "load_ms": 0,
                "render_ms": 0,
                "elapsed_ms": int((_time.perf_counter() - t0) * 1000),
            }

        try:
            fxp_loaded, err = self.ensure_synth(fxp_path, plugin_path)
            load_ms = int((_time.perf_counter() - t0) * 1000)
            if err:
                return {
                    "ok": False,
                    "error": err,
                    "engine": engine_kind,
                    "load_ms": load_ms,
                }
            # Explicit preset required but not on the synth → refuse to render init sound
            if fxp_path and not fxp_loaded:
                return {
                    "ok": False,
                    "error": f"preset not loaded: {fxp_path}",
                    "engine": engine_kind,
                    "load_ms": load_ms,
                }
            assert self.eng is not None and self.synth is not None

            self.eng.set_bpm(float(bpm))
            macros_applied = apply_macros(self.synth, macro_vals, engine=engine_kind)

            self.synth.clear_midi()
            # beats=True — DawDreamer default is seconds
            for n in render_notes:
                midi = int(n["midi"])
                start = float(n["start_beat"])
                dur = max(0.05, float(n["duration_beats"]))
                vel = int(n.get("velocity", n.get("vel", 100)))
                vel = max(1, min(127, vel))
                self.synth.add_midi_note(midi, vel, start, dur, beats=True)

            self.eng.load_graph([(self.synth, [])])
            t_render = _time.perf_counter()
            self.eng.render(duration_sec)
            audio = self.eng.get_audio()
            render_ms = int((_time.perf_counter() - t_render) * 1000)
            latency = 0
            try:
                latency = int(self.synth.get_latency_samples() or 0)
            except Exception:
                latency = 0
            slot = self._slots.get(engine_kind)
            if slot:
                slot.renders += 1
            self.renders = sum(s.renders for s in self._slots.values())
        except Exception as exc:
            # Drop only this engine — the other Serum can stay warm
            self._drop_slot(engine_kind)
            return {"ok": False, "error": str(exc), "engine": engine_kind}

        if audio is None:
            return {"ok": False, "error": "render returned no audio", "engine": engine_kind}

        if latency > 0 and audio.shape[1] > latency + 64:
            audio = audio[:, latency:]

        onset_shift = 0
        first_note_beat = 0.0
        if render_notes:
            first_note_beat = min(float(n["start_beat"]) for n in render_notes)
        expected_first = int(round(first_note_beat * (60.0 / float(bpm)) * SAMPLE_RATE))
        onset = _find_audio_onset(audio)
        if onset is not None:
            onset_shift = int(onset - expected_first)
            if onset_shift > 0 and audio.shape[1] > onset_shift + 64:
                audio = audio[:, onset_shift:]
            elif onset_shift < 0:
                pad = -onset_shift
                audio = np.pad(audio, ((0, 0), (pad, 0)))
                onset_shift = -pad

        # Trim the rendered period first, then tile out to the full loop.
        period = max(1, int(round(duration_sec * SAMPLE_RATE)))
        n = audio.shape[1]
        if n < period:
            audio = np.pad(audio, ((0, 0), (0, period - n)))
        elif n > period:
            audio = audio[:, :period]
        if tile_n > 1:
            audio = np.tile(audio, (1, tile_n))

        target = max(1, int(round(out_duration_sec * SAMPLE_RATE)))
        n = audio.shape[1]
        if n < target:
            audio = np.pad(audio, ((0, 0), (0, target - n)))
        elif n > target:
            audio = audio[:, :target]

        peak = float(np.max(np.abs(audio)))
        audio = np.clip(audio, -1.0, 1.0)
        pcm = (audio.T * 32767.0).astype(np.int16)

        dest = Path(out_path) if out_path else cache_wav
        dest.parent.mkdir(parents=True, exist_ok=True)
        wavfile.write(str(dest), SAMPLE_RATE, pcm)

        return {
            "ok": True,
            "cached": False,
            "wav": str(dest),
            "peak": peak,
            "fxp_loaded": fxp_loaded,
            "macros_applied": macros_applied,
            "macros": macro_vals,
            "plugin": str(plugin),
            "engine": engine_kind,
            "duration_sec": out_duration_sec,
            "render_bars": render_bars,
            "tiled": tile_n > 1,
            "sample_rate": SAMPLE_RATE,
            "latency_samples": latency,
            "onset_shift_samples": onset_shift,
            "onset_detected_sample": onset,
            "expected_first_sample": expected_first,
            "target_samples": target,
            "warm": True,
            "load_ms": load_ms,
            "render_ms": render_ms,
            "elapsed_ms": int((_time.perf_counter() - t0) * 1000),
        }


def inspect_macros(
    fxp_path: str | Path | None,
    *,
    plugin_path: str | Path | None = None,
) -> dict[str, Any]:
    """Load preset and return macros (cold one-shot; worker uses SerumSession)."""
    return SerumSession().inspect_macros(fxp_path, plugin_path=plugin_path)


def render_midi(
    notes: list[dict[str, Any]],
    *,
    bpm: float = 140.0,
    bars: int = 4,
    fxp_path: str | Path | None = None,
    plugin_path: str | Path | None = None,
    out_path: str | Path | None = None,
    use_cache: bool = True,
    macros: list[float] | None = None,
) -> dict[str, Any]:
    """
    Render monophonic-ish MIDI notes through Serum 1 or 2.

    notes: [{midi, start_beat, duration_beats, velocity?}, ...]
    macros: optional floats 0..1 for macro knobs (None = leave preset defaults).
    """
    return SerumSession().render_midi(
        notes,
        bpm=bpm,
        bars=bars,
        fxp_path=fxp_path,
        plugin_path=plugin_path,
        out_path=out_path,
        use_cache=use_cache,
        macros=macros,
    )


def _find_audio_onset(
    audio: "np.ndarray",
    *,
    abs_thresh: float = 0.02,
    rel_thresh: float = 0.08,
    smooth: int = 32,
) -> int | None:
    """
    Return sample index of first significant attack in (channels, samples) audio.
    None if signal is essentially silent.
    """
    if audio is None or audio.size == 0:
        return None
    mono = np.mean(np.abs(audio.astype(np.float64)), axis=0)
    peak = float(np.max(mono)) if mono.size else 0.0
    if peak < 1e-6:
        return None
    if smooth > 1 and mono.size > smooth:
        kernel = np.ones(smooth, dtype=np.float64) / float(smooth)
        env = np.convolve(mono, kernel, mode="same")
    else:
        env = mono
    thr = max(abs_thresh * peak, rel_thresh * peak)
    # Require a short run above threshold so noise ticks don't win
    run = max(4, smooth // 4)
    above = env >= thr
    if not np.any(above):
        return int(np.argmax(env))
    for i in range(0, len(above) - run):
        if above[i] and np.all(above[i : i + run]):
            return int(i)
    return int(np.argmax(env))


def measure_onset_errors_ms(
    wav_path: str | Path,
    *,
    bpm: float,
    note_start_beats: list[float],
    search_radius_ms: float = 45.0,
) -> dict[str, Any]:
    """
    Compare detected *attacks* in a bounce to expected beat times.
    Uses envelope flux (rise) so sustained tails from the previous note
    don't register as early onsets. Used by automated sync tests.
    """
    from scipy.io import wavfile

    sr, pcm = wavfile.read(str(wav_path))
    if pcm.ndim == 2:
        mono = pcm.astype(np.float64).mean(axis=1)
    else:
        mono = pcm.astype(np.float64)
    peak = float(np.max(np.abs(mono))) + 1e-12
    mono = np.abs(mono) / peak
    env = np.convolve(mono, np.ones(64) / 64.0, mode="same")
    # Half-wave flux: only positive rises count as attacks
    flux = np.diff(env, prepend=env[:1])
    flux = np.maximum(flux, 0.0)
    radius = int(round((search_radius_ms / 1000.0) * sr))
    errors_ms: list[float] = []
    details: list[dict[str, Any]] = []
    for beat in note_start_beats:
        exp = int(round(float(beat) * (60.0 / float(bpm)) * sr))
        lo = max(0, exp - radius)
        hi = min(len(flux), exp + radius)
        seg = flux[lo:hi]
        if seg.size == 0:
            continue
        # Peak flux in window = strongest attack
        rel = int(np.argmax(seg))
        # Refine: first sample near peak that exceeds 40% of peak flux
        peak_f = float(seg[rel])
        thr = max(1e-6, 0.4 * peak_f)
        refined = rel
        for j in range(max(0, rel - 32), rel + 1):
            if seg[j] >= thr:
                refined = j
                break
        onset = lo + refined
        err_ms = 1000.0 * (onset - exp) / float(sr)
        errors_ms.append(err_ms)
        details.append(
            {
                "beat": float(beat),
                "expected_sample": exp,
                "onset_sample": onset,
                "error_ms": err_ms,
                "flux_peak": peak_f,
            }
        )
    arr = np.array(errors_ms, dtype=np.float64) if errors_ms else np.array([0.0])
    return {
        "count": len(errors_ms),
        "errors_ms": errors_ms,
        "mean_abs_ms": float(np.mean(np.abs(arr))),
        "max_abs_ms": float(np.max(np.abs(arr))),
        "mean_ms": float(np.mean(arr)),
        "details": details,
        "sample_rate": int(sr),
    }


def grid_to_notes(
    grid: list[dict | None],
    *,
    key: str,
    octave: int,
    bars: int = 4,
) -> list[dict[str, Any]]:
    """Convert 16-step degree grid to beat-based notes (needs midi.js logic in Python)."""
    note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    major = [0, 2, 4, 5, 7, 9, 11]
    minor = [0, 2, 3, 5, 7, 8, 10]
    raw = (key or "C minor").strip()

    m = re.match(r"([A-G])(#|b)?\s*(major|minor|maj|min)?", raw, re.I)
    if not m:
        root, quality = 0, "minor"
    else:
        name = m.group(1).upper() + (m.group(2) or "")
        flat_map2 = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}
        if name in flat_map2:
            name = flat_map2[name]
        root = note_names.index(name) if name in note_names else 0
        q = (m.group(3) or "minor").lower()
        quality = "major" if q in ("major", "maj") else "minor"
    ints = major if quality == "major" else minor

    def deg_to_midi(degree: int, octv: int) -> int:
        d = degree % 7
        return (octv + 1) * 12 + root + ints[d]

    notes: list[dict[str, Any]] = []
    steps = len(grid) or 16
    for bar in range(bars):
        for s, cell in enumerate(grid):
            if not cell:
                continue
            degree = int(cell.get("degree", 0))
            length = int(cell.get("length", 1))
            vel = int(cell.get("vel", 100))
            step = bar * steps + s
            start_beat = step / 4.0  # 16ths
            dur_beats = max(0.05, length / 4.0)
            notes.append(
                {
                    "midi": deg_to_midi(degree, octave),
                    "start_beat": start_beat,
                    "duration_beats": dur_beats,
                    "velocity": vel,
                }
            )
    return notes
