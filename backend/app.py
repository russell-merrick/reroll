"""
Austin Russell Loop Machine — FastAPI backend.

Run from project root:
  python -m uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000

Then open: http://127.0.0.1:8000
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .catalog import CATALOG
from .generate import generate_loop, generate_tracks, reroll_slot
from .scanner import scan_library

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
HOST_DIR = ROOT / "host"
HOST_CACHE = HOST_DIR / "cache"
HOST_CACHE.mkdir(parents=True, exist_ok=True)
EXPORT_DIR = ROOT / "exports"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
(EXPORT_DIR / "audio").mkdir(parents=True, exist_ok=True)
(EXPORT_DIR / "midi").mkdir(parents=True, exist_ok=True)
SAVES_DIR = ROOT / "saves"
SAVES_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_PATH = ROOT / "user_settings.json"

AUDIO_MEDIA = {
    ".wav": "audio/wav",
    ".aif": "audio/aiff",
    ".aiff": "audio/aiff",
    ".flac": "audio/flac",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
}

app = FastAPI(title="Austin Russell Loop Machine", version="0.1.0")


class GenerateRequest(BaseModel):
    bpm: int = 140
    key: str = "F minor"
    style: str = "Techno"
    locked: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # role -> s1 | s2 | both  (bass/lead Serum engine filter)
    serum_engines: dict[str, str] = Field(default_factory=dict)
    # role -> bass | lead | arp | pad | … | any
    serum_types: dict[str, str] = Field(default_factory=dict)
    # Dynamic track stack: [{id, type, locked, path, serum_engine, serum_type, ...}]
    tracks: list[dict[str, Any]] | None = None
    filter_risers: bool = False
    filter_factory_serum: bool = False


class RerollRequest(BaseModel):
    slot: str
    current_path: str | None = None
    serum_engine: str = "both"
    serum_type: str = "any"
    filter_risers: bool = False
    filter_factory_serum: bool = False


class MidiNote(BaseModel):
    midi: int
    start_beat: float
    duration_beats: float
    velocity: int = 100


class SerumRenderRequest(BaseModel):
    """Render bass/lead through local Serum (DawDreamer on Python 3.12)."""

    role: str = "bass"
    bpm: float = 140
    bars: int = 4
    key: str = "F minor"
    octave: int = 2
    fxp: str | None = None  # absolute path to .fxp
    # either notes OR grid (16-step degree cells)
    notes: list[MidiNote] | None = None
    grid: list[dict[str, Any] | None] | None = None
    # optional MACRO 1–4 (0..1). None = leave preset defaults.
    macros: list[float] | None = None


class SerumMacrosRequest(BaseModel):
    fxp: str


class SerumOpenRequest(BaseModel):
    """Open Serum plugin UI (DawDreamer editor), optionally with a .fxp loaded."""

    fxp: str | None = None


class SaveLoopRequest(BaseModel):
    """Persist a named loop (session + tracks + MIDI) as JSON under saves/."""

    name: str
    bpm: int = 140
    key: str = "F minor"
    style: str = "Techno"
    options: dict[str, Any] = Field(default_factory=dict)
    track_order: list[str] = Field(default_factory=list)
    slots: dict[str, Any] = Field(default_factory=dict)
    id: str | None = None  # overwrite existing if provided


class UserSettings(BaseModel):
    """Persistent UI prefs (Options + session BPM/key/style)."""

    bpm: int = 140
    key: str = "F minor"
    style: str = "Techno"
    filterRisers: bool = True
    filterFactorySerum: bool = False
    serum1: bool = True
    serum2: bool = True
    # instrument id → enabled (default track stack)
    instruments: dict[str, bool] = Field(default_factory=dict)


def _default_settings() -> dict[str, Any]:
    return UserSettings().model_dump()


def _read_user_settings() -> dict[str, Any]:
    if not SETTINGS_PATH.is_file():
        return _default_settings()
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_settings()
    if not isinstance(data, dict):
        return _default_settings()
    base = _default_settings()
    base.update({k: data[k] for k in base if k in data})
    # Clamp BPM
    try:
        bpm = int(base.get("bpm", 140))
        base["bpm"] = max(60, min(200, bpm))
    except (TypeError, ValueError):
        base["bpm"] = 140
    if "filterRisers" in data:
        base["filterRisers"] = bool(data.get("filterRisers"))
    else:
        base["filterRisers"] = True
    base["filterFactorySerum"] = bool(base.get("filterFactorySerum", False))
    base["serum1"] = bool(base.get("serum1", True))
    base["serum2"] = bool(base.get("serum2", True))
    inst = base.get("instruments")
    base["instruments"] = dict(inst) if isinstance(inst, dict) else {}
    base["key"] = str(base.get("key") or "F minor")
    base["style"] = str(base.get("style") or "Techno")
    return base


def _write_user_settings(data: dict[str, Any]) -> dict[str, Any]:
    merged = _default_settings()
    for k in merged:
        if k in data:
            merged[k] = data[k]
    # Re-normalize via reader rules
    try:
        bpm = int(merged.get("bpm", 140))
        merged["bpm"] = max(60, min(200, bpm))
    except (TypeError, ValueError):
        merged["bpm"] = 140
    if "filterRisers" in data:
        merged["filterRisers"] = bool(data.get("filterRisers"))
    else:
        merged["filterRisers"] = True
    merged["filterFactorySerum"] = bool(merged.get("filterFactorySerum", False))
    merged["serum1"] = bool(merged.get("serum1", True))
    merged["serum2"] = bool(merged.get("serum2", True))
    inst = merged.get("instruments")
    if isinstance(inst, dict):
        merged["instruments"] = {str(k): bool(v) for k, v in inst.items()}
    else:
        merged["instruments"] = {}
    merged["key"] = str(merged.get("key") or "F minor")
    merged["style"] = str(merged.get("style") or "Techno")
    SETTINGS_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return merged


def _find_py312() -> tuple[list[str], str] | None:
    """Return (cmd_prefix, label) for invoking host CLI on Python 3.12."""
    direct = Path.home() / "AppData/Local/Programs/Python/Python312/python.exe"
    if direct.is_file():
        return [str(direct)], str(direct)
    # common install path
    for p in Path(r"C:\Users").glob("*/AppData/Local/Programs/Python/Python312/python.exe"):
        if p.is_file():
            return [str(p)], str(p)
    py = shutil.which("py")
    if py:
        return [py, "-3.12"], f"{py} -3.12"
    return None


def _known_paths() -> set[str]:
    """Absolute paths allowed for audio streaming (catalog only)."""
    out: set[str] = set()
    for a in CATALOG.samples:
        try:
            out.add(str(Path(a.path).resolve()))
        except OSError:
            continue
    return out


@app.on_event("startup")
def startup_scan() -> None:
    scan_library(CATALOG)

    def _warm_serum_worker() -> None:
        try:
            _HOST_WORKER.call({"action": "ping"}, timeout=45.0)
        except Exception:
            pass  # first real render will retry

    threading.Thread(target=_warm_serum_worker, name="serum-warm", daemon=True).start()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/library")
def library_summary() -> dict[str, Any]:
    return CATALOG.summary()


@app.post("/api/scan")
def rescan() -> dict[str, Any]:
    scan_library(CATALOG)
    return CATALOG.summary()


@app.get("/api/samples")
def list_samples(role: str | None = None, limit: int = 100) -> dict[str, Any]:
    items = CATALOG.samples
    if role:
        items = [a for a in items if a.role == role.lower()]
    return {
        "count": len(items),
        "items": [a.to_dict() for a in items[: max(1, min(limit, 500))]],
    }


@app.get("/api/audio")
def stream_audio(path: str = Query(..., description="Absolute path of a catalog sample")):
    """Stream a local sample for browser preview. Only catalog paths are allowed."""
    if not CATALOG.scanned:
        scan_library(CATALOG)

    raw = unquote(path)
    try:
        file_path = Path(raw).expanduser().resolve()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid path: {exc}") from exc

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found on disk")

    allowed = _known_paths()
    if str(file_path) not in allowed:
        # Case-insensitive fallback for Windows
        lower_map = {p.lower(): p for p in allowed}
        if str(file_path).lower() not in lower_map:
            raise HTTPException(
                status_code=403,
                detail="Path not in scanned library. Rescan first.",
            )

    ext = file_path.suffix.lower()
    media = AUDIO_MEDIA.get(ext) or mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    return FileResponse(
        path=str(file_path),
        media_type=media,
        filename=file_path.name,
        headers={"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"},
    )


@app.post("/api/generate")
def api_generate(body: GenerateRequest) -> dict[str, Any]:
    if not CATALOG.scanned:
        scan_library(CATALOG)
    if not CATALOG.samples and not CATALOG.serum:
        raise HTTPException(
            status_code=400,
            detail="Catalog is empty. Check sample/Serum paths and hit Rescan.",
        )
    if body.tracks:
        return generate_tracks(
            CATALOG,
            body.tracks,
            bpm=body.bpm,
            key=body.key,
            style=body.style,
            filter_risers=bool(body.filter_risers),
            filter_factory_serum=bool(body.filter_factory_serum),
        )
    return generate_loop(
        CATALOG,
        locked=body.locked,
        bpm=body.bpm,
        key=body.key,
        style=body.style,
        serum_engines=body.serum_engines or {},
        serum_types=body.serum_types or {},
        filter_risers=bool(body.filter_risers),
        filter_factory_serum=bool(body.filter_factory_serum),
    )


@app.post("/api/reroll")
def api_reroll(body: RerollRequest) -> dict[str, Any]:
    # Dynamic track types (arp, pad, …) allowed — not only the original 7 slots
    if not body.slot or not str(body.slot).strip():
        raise HTTPException(status_code=400, detail="slot required")
    return reroll_slot(
        CATALOG,
        body.slot,
        current_path=body.current_path,
        serum_engine=body.serum_engine or "both",
        serum_type=body.serum_type or "any",
        filter_risers=bool(body.filter_risers),
        filter_factory_serum=bool(body.filter_factory_serum),
    )


def _assert_fxp_allowed(fxp: str) -> Path:
    """Allow Serum 1 (.fxp) or Serum 2 (.SerumPreset) under Xfer / catalog."""
    fxp_path = Path(fxp)
    if not fxp_path.is_file():
        raise HTTPException(status_code=400, detail=f"preset not found: {fxp}")
    ext = fxp_path.suffix.lower()
    if ext not in (".fxp", ".serumpreset"):
        raise HTTPException(status_code=400, detail=f"unsupported preset type: {ext}")
    allowed = False
    try:
        fxp_res = str(fxp_path.resolve())
        for a in CATALOG.serum:
            if str(Path(a.path).resolve()).lower() == fxp_res.lower():
                allowed = True
                break
        xfer = Path.home() / "Documents" / "Xfer"
        if xfer.exists() and xfer.resolve() in fxp_path.resolve().parents:
            allowed = True
        for sub in ("Serum Presets", "Serum 2 Presets"):
            root = xfer / sub
            if root.exists() and root.resolve() in fxp_path.resolve().parents:
                allowed = True
    except OSError:
        pass
    if not allowed and "xfer" in str(fxp_path).lower():
        allowed = True
    if not allowed:
        raise HTTPException(status_code=403, detail="preset path not in Serum library")
    return fxp_path


def _parse_host_json(text: str) -> dict[str, Any] | None:
    """Parse last JSON object from host stdout/stderr (may include log noise)."""
    raw = (text or "").strip()
    if not raw:
        return None
    # Whole blob is JSON
    try:
        val = json.loads(raw)
        if isinstance(val, dict):
            return val
    except json.JSONDecodeError:
        pass
    # Last {...} line (or trailing object if crash mixed output)
    lines = raw.splitlines()
    for line in reversed(lines):
        line = line.strip()
        if not line.startswith("{"):
            # Sometimes embedded mid-line after a prefix
            brace = line.find("{")
            if brace < 0:
                continue
            line = line[brace:]
        try:
            val = json.loads(line)
            if isinstance(val, dict):
                return val
        except json.JSONDecodeError:
            continue
    # Last-ditch: find final balanced-ish object from last '{'
    idx = raw.rfind("{")
    if idx >= 0:
        try:
            val = json.loads(raw[idx:])
            if isinstance(val, dict):
                return val
        except json.JSONDecodeError:
            pass
    return None


def _read_host_result_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


class _SerumHostWorker:
    """
    Long-lived py3.12 + DawDreamer process. Avoids multi-second cold starts
    on every MIDI/dice/BPM change by keeping Serum loaded.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._next_id = 1
        self._ready = False

    def _kill(self) -> None:
        proc = self._proc
        self._proc = None
        self._ready = False
        if not proc:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except OSError:
            pass

    def _ensure(self) -> None:
        if self._proc is not None and self._proc.poll() is None and self._ready:
            return
        self._kill()
        py_cmd = _find_py312()
        if not py_cmd:
            raise HTTPException(
                status_code=503,
                detail="Python 3.12 not found. Install it and: py -3.12 -m pip install dawdreamer numpy scipy",
            )
        cmd = [*py_cmd[0], str(HOST_DIR / "cli_worker.py")]
        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,  # avoid pipe deadlock if plugin is chatty
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,  # line-buffered
            )
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"failed to start Serum worker: {exc}") from exc

        # Wait for ready line
        assert self._proc.stdout is not None
        deadline = time.time() + 30
        while time.time() < deadline:
            if self._proc.poll() is not None:
                self._kill()
                raise HTTPException(status_code=500, detail="Serum worker failed to start")
            line = self._proc.stdout.readline()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and msg.get("event") == "ready":
                self._ready = True
                return
        self._kill()
        raise HTTPException(status_code=504, detail="Serum worker ready timeout")

    def call(self, payload: dict[str, Any], *, timeout: float = 120) -> dict[str, Any]:
        with self._lock:
            last_err: Exception | None = None
            for _attempt in range(2):
                try:
                    self._ensure()
                    assert self._proc is not None and self._proc.stdin and self._proc.stdout
                    req_id = self._next_id
                    self._next_id += 1
                    body = {**payload, "id": req_id}
                    if "action" not in body:
                        body["action"] = "render"
                    self._proc.stdin.write(json.dumps(body) + "\n")
                    self._proc.stdin.flush()

                    deadline = time.time() + timeout
                    while time.time() < deadline:
                        if self._proc.poll() is not None:
                            raise RuntimeError("Serum worker died mid-request")
                        # Non-blocking-ish read with timeout via short polls
                        line = self._proc.stdout.readline()
                        if not line:
                            time.sleep(0.01)
                            continue
                        try:
                            msg = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(msg, dict):
                            continue
                        # Skip spontaneous events without matching id
                        if msg.get("id") not in (None, req_id) and msg.get("event"):
                            continue
                        if msg.get("id") == req_id or (
                            msg.get("id") is None and msg.get("ok") is not None
                        ):
                            if msg.get("id") is None:
                                msg["id"] = req_id
                            return msg
                    raise TimeoutError("Serum worker timed out")
                except Exception as exc:
                    last_err = exc
                    self._kill()
            raise HTTPException(
                status_code=500,
                detail=f"Serum worker failed: {last_err}",
            ) from last_err


_HOST_WORKER = _SerumHostWorker()


def _run_host_cli_oneshot(payload: dict[str, Any], *, timeout: int = 120) -> dict[str, Any]:
    """Fallback: spawn cli_render.py per job (cold start)."""
    py_cmd = _find_py312()
    if not py_cmd:
        raise HTTPException(
            status_code=503,
            detail="Python 3.12 not found. Install it and: py -3.12 -m pip install dawdreamer numpy scipy",
        )
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        req_path = tmp_path / "req.json"
        result_path = tmp_path / "result.json"
        body = {**payload, "result_path": str(result_path)}
        req_path.write_text(json.dumps(body), encoding="utf-8")
        cmd = [*py_cmd[0], str(HOST_DIR / "cli_render.py"), "--request", str(req_path)]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            partial = _read_host_result_file(result_path)
            if partial is not None and partial.get("ok"):
                return partial
            raise HTTPException(status_code=504, detail="Serum host timed out") from exc

        result = _read_host_result_file(result_path)
        if result is None:
            result = _parse_host_json(proc.stdout or "")
        if result is None:
            result = _parse_host_json(proc.stderr or "")

        if result is not None:
            if result.get("ok"):
                return result
            raise HTTPException(
                status_code=500,
                detail=result.get("error") or "host returned ok=false",
            )

        snippet = (proc.stderr or proc.stdout or "").strip() or "no output"
        if len(snippet) > 800:
            snippet = snippet[:800] + "…"
        if proc.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"host failed (code {proc.returncode}): {snippet}",
            )
        raise HTTPException(status_code=500, detail=f"host produced no JSON: {snippet}")


def _run_host_cli(payload: dict[str, Any], *, timeout: int = 120) -> dict[str, Any]:
    """Prefer warm worker; fall back to one-shot CLI if worker is unhealthy.

    Always kill the worker before oneshot — two concurrent Serum instances often
    hard-crash with STATUS_DLL_INIT_FAILED (0xC0000142) and leave the UI stuck
    on the JS-synth fallback (same 'default' sound for every preset).
    """
    action = payload.get("action") or "render"
    worker_payload = {**payload, "action": action}

    def _oneshot_after_kill() -> dict[str, Any]:
        try:
            _HOST_WORKER._kill()
        except Exception:
            pass
        # Brief pause so Windows can release the VST module
        time.sleep(0.2)
        return _run_host_cli_oneshot(payload, timeout=timeout)

    try:
        result = _HOST_WORKER.call(worker_payload, timeout=float(timeout))
        if result.get("ok"):
            return result
        # Don't fall back for logical errors (missing notes, bad fxp)
        err = str(result.get("error") or "host returned ok=false")
        low = err.lower()
        if "not found" in low or "no notes" in low:
            raise HTTPException(status_code=500, detail=err)
        # Soft fail (preset load, crash recovery) — recycle then cold path
        return _oneshot_after_kill()
    except HTTPException as exc:
        # Worker exhausted retries — still try oneshot if it wasn't a logical 4xx-style error
        detail = str(exc.detail or "")
        low = detail.lower()
        if "not found" in low or "no notes" in low or "python 3.12" in low:
            raise
        return _oneshot_after_kill()
    except Exception:
        return _oneshot_after_kill()

@app.get("/api/serum/status")
def serum_host_status() -> dict[str, Any]:
    """Whether the DawDreamer/Serum host can be invoked."""
    py = _find_py312()
    dll = Path(r"C:\Program Files\Common Files\VST3\Serum_x64.dll")
    s2 = Path(r"C:\Program Files\Common Files\VST3\Serum2.vst3")
    return {
        "python312": py[1] if py else None,
        "serum_dll": dll.is_file(),
        "serum2_vst3": s2.exists(),
        "ready": bool(py) and (dll.is_file() or s2.exists()),
        "serum1_ready": bool(py) and dll.is_file(),
        "serum2_ready": bool(py) and s2.exists(),
        "editor": bool(py) and (dll.is_file() or s2.exists()),
        "note": "Serum1=.fxp+DLL · Serum2=.SerumPreset+VST3 via serum2-preset-loader",
    }


@app.post("/api/serum/open")
def serum_open_editor(body: SerumOpenRequest) -> dict[str, Any]:
    """
    Launch Serum's full plugin UI in a separate process.
    Xfer does not ship a true standalone on this machine — this hosts the VST UI.
    Optionally loads the current slot .fxp first.
    """
    py_cmd = _find_py312()
    if not py_cmd:
        raise HTTPException(
            status_code=503,
            detail="Python 3.12 not found. Install it and: py -3.12 -m pip install dawdreamer",
        )
    dll = Path(r"C:\Program Files\Common Files\VST3\Serum_x64.dll")
    s2 = Path(r"C:\Program Files\Common Files\VST3\Serum2.vst3")
    if not dll.is_file() and not s2.exists():
        raise HTTPException(status_code=503, detail="No Serum plugin found")

    fxp: str | None = None
    if body.fxp:
        fxp = str(_assert_fxp_allowed(body.fxp).resolve())

    script = HOST_DIR / "cli_open_editor.py"
    cmd = [*py_cmd[0], str(script)]
    if fxp:
        cmd.extend(["--fxp", fxp])

    # Detach so the editor stays open independent of the API request
    creationflags = 0
    if sys.platform == "win32":
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        )

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"failed to launch Serum UI: {exc}") from exc

    return {
        "ok": True,
        "pid": proc.pid,
        "fxp": fxp,
        "note": "Plugin UI process started (not a true Xfer standalone app)",
    }


@app.post("/api/serum/macros")
def serum_macros(body: SerumMacrosRequest) -> dict[str, Any]:
    """Read MACRO 1–4 defaults from a .fxp (after load)."""
    _assert_fxp_allowed(body.fxp)
    result = _run_host_cli({"action": "macros", "fxp": body.fxp}, timeout=60)
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "macro inspect failed"))
    return result


@app.post("/api/serum/render")
def serum_render(body: SerumRenderRequest) -> dict[str, Any]:
    """
    Offline-render a Serum pass for one role.
    Spawns Python 3.12 + host/cli_render.py (DawDreamer).
    """
    if body.fxp:
        _assert_fxp_allowed(body.fxp)

    payload: dict[str, Any] = {
        "bpm": body.bpm,
        "bars": body.bars,
        "key": body.key,
        "octave": body.octave,
        "fxp": body.fxp,
        "use_cache": True,
    }
    if body.macros is not None:
        payload["macros"] = [max(0.0, min(1.0, float(v))) for v in body.macros[:4]]
    if body.notes:
        payload["notes"] = [n.model_dump() for n in body.notes]
    elif body.grid is not None:
        payload["grid"] = body.grid
    else:
        raise HTTPException(status_code=400, detail="Provide notes or grid")

    result = _run_host_cli(payload, timeout=120)

    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "render failed"))

    wav = result.get("wav")
    if not wav or not Path(wav).is_file():
        raise HTTPException(status_code=500, detail="render missing wav")

    # URL for browser playback
    result["url"] = f"/api/serum/audio?path={Path(wav).name}"
    result["role"] = body.role
    return result


@app.get("/api/serum/audio")
def serum_audio(path: str = Query(..., description="Cache filename only")):
    """Serve a rendered Serum WAV from host/cache (filename only, no paths)."""
    name = Path(path).name
    if name != path or ".." in name or "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="invalid path")
    file_path = (HOST_CACHE / name).resolve()
    if not str(file_path).lower().startswith(str(HOST_CACHE.resolve()).lower()):
        raise HTTPException(status_code=403, detail="forbidden")
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(
        path=str(file_path),
        media_type="audio/wav",
        filename=name,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@app.get("/api/export/path")
def export_path() -> dict[str, Any]:
    """Return the export folder path (creates audio/ + midi/ if missing)."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    (EXPORT_DIR / "audio").mkdir(parents=True, exist_ok=True)
    (EXPORT_DIR / "midi").mkdir(parents=True, exist_ok=True)
    return {"ok": True, "path": str(EXPORT_DIR.resolve())}


@app.post("/api/export/open")
def export_open_folder() -> dict[str, Any]:
    """Open the export folder in the OS file manager (Explorer on Windows)."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    (EXPORT_DIR / "audio").mkdir(parents=True, exist_ok=True)
    (EXPORT_DIR / "midi").mkdir(parents=True, exist_ok=True)
    path = str(EXPORT_DIR.resolve())
    try:
        if sys.platform == "win32":
            # os.startfile opens Explorer without a hanging console process
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not open folder: {exc}") from exc
    return {"ok": True, "path": path}


def _slug_name(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", name.strip(), flags=re.UNICODE)
    s = re.sub(r"[-\s]+", "-", s).strip("-").lower()
    return (s[:48] if s else "loop")


def _loop_path(loop_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", loop_id)
    if not safe or safe != loop_id:
        raise HTTPException(status_code=400, detail="invalid loop id")
    return SAVES_DIR / f"{safe}.json"


def _read_loop_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"corrupt save: {path.name}") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail=f"invalid save: {path.name}")
    return data


def _loop_summary(data: dict[str, Any]) -> dict[str, Any]:
    order = data.get("track_order") or []
    return {
        "id": data.get("id"),
        "name": data.get("name") or "Untitled",
        "bpm": data.get("bpm"),
        "key": data.get("key"),
        "style": data.get("style"),
        "saved_at": data.get("saved_at"),
        "track_count": len(order) if isinstance(order, list) else 0,
    }


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    """Load persisted user settings (Options + session defaults)."""
    return {"ok": True, "settings": _read_user_settings()}


@app.put("/api/settings")
@app.post("/api/settings")
def save_settings(body: UserSettings) -> dict[str, Any]:
    """Save user settings to user_settings.json."""
    saved = _write_user_settings(body.model_dump())
    return {"ok": True, "settings": saved}


@app.get("/api/loops")
def list_loops() -> dict[str, Any]:
    """List saved loops (newest first)."""
    SAVES_DIR.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for path in SAVES_DIR.glob("*.json"):
        try:
            data = _read_loop_file(path)
            if not data.get("id"):
                data["id"] = path.stem
            items.append(_loop_summary(data))
        except HTTPException:
            continue
    items.sort(key=lambda x: x.get("saved_at") or "", reverse=True)
    return {"count": len(items), "items": items}


@app.get("/api/loops/{loop_id}")
def get_loop(loop_id: str) -> dict[str, Any]:
    path = _loop_path(loop_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="loop not found")
    data = _read_loop_file(path)
    data.setdefault("id", loop_id)
    return data


@app.post("/api/loops")
def save_loop(body: SaveLoopRequest) -> dict[str, Any]:
    """Save or overwrite a named loop."""
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    if not body.track_order:
        raise HTTPException(status_code=400, detail="no tracks to save")

    SAVES_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    loop_id = body.id
    if loop_id:
        try:
            path = _loop_path(loop_id)
        except HTTPException:
            loop_id = None
            path = None  # type: ignore[assignment]
        else:
            if not path.is_file():
                loop_id = None
    if not loop_id:
        loop_id = f"{_slug_name(name)}-{uuid.uuid4().hex[:8]}"
        path = _loop_path(loop_id)

    doc: dict[str, Any] = {
        "id": loop_id,
        "name": name,
        "bpm": int(body.bpm),
        "key": body.key,
        "style": body.style,
        "options": body.options or {},
        "track_order": list(body.track_order),
        "slots": body.slots or {},
        "saved_at": now,
        "version": 1,
    }
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return {"ok": True, **_loop_summary(doc)}


@app.delete("/api/loops/{loop_id}")
def delete_loop(loop_id: str) -> dict[str, Any]:
    path = _loop_path(loop_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="loop not found")
    try:
        path.unlink()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "id": loop_id}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


@app.get("/styles.css")
def styles() -> FileResponse:
    return FileResponse(FRONTEND / "styles.css", media_type="text/css")


@app.get("/app.js")
def script() -> FileResponse:
    return FileResponse(FRONTEND / "app.js", media_type="application/javascript")


@app.get("/midi.js")
def midi_script() -> FileResponse:
    return FileResponse(FRONTEND / "midi.js", media_type="application/javascript")
