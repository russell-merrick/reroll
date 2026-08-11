"""Export a session loop for Ableton — flat files + drag-friendly paths."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def _slug(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (name or "").strip(), flags=re.UNICODE)
    s = re.sub(r"[-\s]+", "-", s).strip("-").lower()
    return (s[:40] if s else "loop")


def _safe_stem(name: str, fallback: str) -> str:
    base = Path(str(name or "")).stem or fallback
    s = re.sub(r"[^\w\s.-]", "", base, flags=re.UNICODE)
    s = re.sub(r"\s+", "_", s).strip("._")
    return (s[:40] if s else fallback)


def _is_serum_path(path: str | None) -> bool:
    if not path:
        return False
    return Path(path).suffix.lower() in (".fxp", ".serumpreset")


def _mime_for(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".wav": "audio/wav",
        ".aif": "audio/aiff",
        ".aiff": "audio/aiff",
        ".flac": "audio/flac",
        ".mp3": "audio/mpeg",
        ".mid": "audio/midi",
        ".midi": "audio/midi",
    }.get(ext, "application/octet-stream")


def ableton_user_library_samples() -> Path | None:
    """Default Ableton User Library Samples folder (Windows), if present."""
    home = Path.home()
    candidates = [
        home / "Documents" / "Ableton" / "User Library" / "Samples",
        home / "OneDrive" / "Documents" / "Ableton" / "User Library" / "Samples",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    # Prefer creating under Documents/Ableton if parent exists
    docs = home / "Documents" / "Ableton" / "User Library" / "Samples"
    try:
        docs.mkdir(parents=True, exist_ok=True)
        return docs
    except OSError:
        return None


def _mirror_flat(files: list[Path], dest_dir: Path) -> list[str]:
    """Copy files into dest_dir (cleared first). Returns absolute paths written."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    for old in dest_dir.iterdir():
        if old.is_file() and old.name not in (".gitkeep",):
            try:
                old.unlink()
            except OSError:
                pass
    out: list[str] = []
    for src in files:
        if not src.is_file():
            continue
        dest = dest_dir / src.name
        shutil.copy2(src, dest)
        out.append(str(dest.resolve()))
    return out


def export_loop(
    *,
    export_root: Path,
    bpm: float,
    key: str,
    style: str,
    bars: int,
    tracks: list[dict[str, Any]],
    name: str | None = None,
    render_serum: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    sync_ableton_drop: bool = True,
    sync_user_library: bool = True,
    write_als: bool = True,
) -> dict[str, Any]:
    """
    Write a flat export folder (no audio/midi subdirs) for easy multi-select drag.

    Also mirrors into:
      - exports/ABLETON_DROP/  (always the latest set)
      - ~/Documents/Ableton/User Library/Samples/Reroll/  (when possible)
        so clips appear in Live's browser without leaving Live.

    When ``write_als`` is true, also builds an Ableton Live Set project folder
    (``.als`` + ``Samples/Imported``) next to the flat stems.
    """
    from .midi_util import grid_to_notes, write_midi_file

    export_root = Path(export_root)
    export_root.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    label = _slug(name or f"{style or 'loop'}-{key or 'key'}-{int(bpm)}bpm")
    folder = export_root / f"{stamp}_{label}"
    folder.mkdir(parents=True, exist_ok=True)

    bars = max(1, min(32, int(bars or 4)))
    bpm = float(bpm or 140)
    key = key or "F minor"
    style = style or "Techno"

    files_out: list[dict[str, Any]] = []
    written: list[Path] = []
    errors: list[str] = []
    idx = 0

    def next_name(base: str, ext: str) -> str:
        nonlocal idx
        idx += 1
        return f"{idx:02d}_{_safe_stem(base, 'track')}{ext}"

    for t in tracks:
        if not isinstance(t, dict):
            continue
        tid = str(t.get("id") or t.get("role") or "track")
        ttype = str(t.get("type") or tid.split("__")[0] or "track")
        path = t.get("path")
        display = str(t.get("name") or Path(str(path or "")).name or tid)
        kind = str(t.get("kind") or ("serum" if _is_serum_path(path) else "sample"))
        midi_state = t.get("midi") if isinstance(t.get("midi"), dict) else None
        # Prefer sample/preset name so Live multi-import track names match the sound
        label_stem = f"{tid}_{_safe_stem(display, ttype)}"

        # --- Audio ---
        if path and _is_serum_path(str(path)):
            if render_serum is None:
                errors.append(f"{tid}: Serum render unavailable")
            else:
                try:
                    grid = None
                    if midi_state and isinstance(midi_state.get("grid"), list):
                        grid = midi_state["grid"]
                    payload: dict[str, Any] = {
                        "role": tid,
                        "bpm": bpm,
                        "bars": bars,
                        "key": midi_state.get("key") if midi_state else key,
                        "octave": int(
                            (midi_state or {}).get(
                                "octave", 2 if ttype == "bass" else 4
                            )
                        ),
                        "fxp": str(path),
                        "use_cache": True,
                    }
                    if grid is not None:
                        payload["grid"] = grid
                    else:
                        payload["grid"] = [
                            {"degree": 0, "length": 16, "vel": 100}
                        ] + [None] * 15
                    macros = t.get("macros")
                    if isinstance(macros, list) and macros:
                        payload["macros"] = [
                            max(0.0, min(1.0, float(v))) for v in macros[:8]
                        ]
                    result = render_serum(payload)
                    wav = result.get("wav")
                    if not result.get("ok") or not wav or not Path(wav).is_file():
                        errors.append(
                            f"{tid}: Serum bounce failed · {result.get('error') or 'no wav'}"
                        )
                    else:
                        fname = next_name(label_stem, ".wav")
                        dest = folder / fname
                        shutil.copy2(wav, dest)
                        written.append(dest)
                        files_out.append(
                            {
                                "track": tid,
                                "type": ttype,
                                "kind": "serum",
                                "role": "audio",
                                "name": fname,
                                "file": fname,
                                "abs_path": str(dest.resolve()),
                                "mime": "audio/wav",
                                "source": str(path),
                            }
                        )
                except Exception as exc:
                    errors.append(f"{tid}: Serum export error · {exc}")
        elif path and Path(path).is_file():
            # Render full session loop (patterns / phrase beds), not a single one-shot file
            src = Path(path)
            fname = next_name(label_stem, ".wav")
            dest = folder / fname
            try:
                from .render_sample_loop import render_sample_loop

                rendered = render_sample_loop(
                    src,
                    dest,
                    track_type=ttype,
                    bpm=bpm,
                    bars=bars,
                    name_blob=f"{display} {src.name}",
                )
                if rendered.get("ok") and dest.is_file():
                    written.append(dest)
                    files_out.append(
                        {
                            "track": tid,
                            "type": ttype,
                            "kind": "sample_loop",
                            "role": "audio",
                            "name": fname,
                            "file": fname,
                            "abs_path": str(dest.resolve()),
                            "mime": "audio/wav",
                            "source": str(src.resolve()),
                            "render_mode": rendered.get("mode"),
                            "duration_sec": rendered.get("duration_sec"),
                        }
                    )
                else:
                    # Fallback: copy original one-shot if offline render fails
                    err = rendered.get("error") or "render failed"
                    errors.append(f"{tid}: loop render failed ({err}) — copied raw sample")
                    ext = src.suffix.lower() or ".wav"
                    fname2 = next_name(label_stem, ext)
                    dest2 = folder / fname2
                    shutil.copy2(src, dest2)
                    written.append(dest2)
                    files_out.append(
                        {
                            "track": tid,
                            "type": ttype,
                            "kind": "sample",
                            "role": "audio",
                            "name": fname2,
                            "file": fname2,
                            "abs_path": str(dest2.resolve()),
                            "mime": _mime_for(dest2),
                            "source": str(src.resolve()),
                        }
                    )
            except Exception as exc:
                errors.append(f"{tid}: loop render error · {exc}")
                try:
                    ext = src.suffix.lower() or ".wav"
                    fname2 = next_name(label_stem, ext)
                    dest2 = folder / fname2
                    shutil.copy2(src, dest2)
                    written.append(dest2)
                    files_out.append(
                        {
                            "track": tid,
                            "type": ttype,
                            "kind": "sample",
                            "role": "audio",
                            "name": fname2,
                            "file": fname2,
                            "abs_path": str(dest2.resolve()),
                            "mime": _mime_for(dest2),
                            "source": str(src.resolve()),
                        }
                    )
                except OSError as exc2:
                    errors.append(f"{tid}: copy failed · {exc2}")
        elif path:
            errors.append(f"{tid}: missing file · {path}")
        elif kind == "serum":
            errors.append(f"{tid}: no Serum preset path to bounce")

        # --- MIDI ---
        if midi_state and isinstance(midi_state.get("grid"), list):
            try:
                notes = grid_to_notes(
                    midi_state["grid"],
                    key=str(midi_state.get("key") or key),
                    octave=int(midi_state.get("octave", 3)),
                    bars=bars,
                )
                if notes:
                    fname = next_name(f"{label_stem}_midi", ".mid")
                    mid_path = folder / fname
                    write_midi_file(
                        mid_path,
                        notes,
                        bpm=bpm,
                        track_name=tid[:32],
                    )
                    written.append(mid_path)
                    files_out.append(
                        {
                            "track": tid,
                            "type": ttype,
                            "kind": "midi",
                            "role": "midi",
                            "name": fname,
                            "file": fname,
                            "abs_path": str(mid_path.resolve()),
                            "mime": "audio/midi",
                            "notes": len(notes),
                        }
                    )
            except Exception as exc:
                errors.append(f"{tid}: MIDI write failed · {exc}")

    # --- Mirrors for "always the same place" + Live browser ---
    drop_dir = export_root / "ABLETON_DROP"
    drop_paths: list[str] = []
    if sync_ableton_drop and written:
        try:
            drop_paths = _mirror_flat(written, drop_dir)
        except OSError as exc:
            errors.append(f"ABLETON_DROP mirror failed · {exc}")

    user_lib_dir: str | None = None
    user_lib_paths: list[str] = []
    if sync_user_library and written:
        samples_root = ableton_user_library_samples()
        if samples_root is not None:
            lib_dir = samples_root / "Reroll"
            try:
                user_lib_paths = _mirror_flat(written, lib_dir)
                user_lib_dir = str(lib_dir.resolve())
            except OSError as exc:
                errors.append(f"User Library mirror failed · {exc}")

    # Back-compat keys for older UI
    audio_out = [f for f in files_out if f.get("role") == "audio"]
    midi_out = [f for f in files_out if f.get("role") == "midi"]

    als_info: dict[str, Any] | None = None
    if write_als and audio_out:
        try:
            from .export_als import write_als_project

            als_audio = [
                {
                    "name": f.get("name"),
                    "abs_path": f.get("abs_path"),
                    "track": Path(str(f.get("name") or "track")).stem,
                }
                for f in audio_out
                if f.get("abs_path")
            ]
            # Write .als into THIS export folder (next to the wavs) so it is obvious
            als_info = write_als_project(
                parent_dir=folder,
                project_name=name or label,
                bpm=bpm,
                bars=bars,
                audio_files=als_audio,
                nest_project_folder=False,
            )
            if not als_info.get("ok"):
                errors.append(
                    f"ALS project: {als_info.get('error') or 'failed'}"
                )
            else:
                als_path = als_info.get("als_path")
                if als_path:
                    files_out.append(
                        {
                            "track": "live_set",
                            "type": "ableton",
                            "kind": "als",
                            "role": "als",
                            "name": Path(str(als_path)).name,
                            "file": Path(str(als_path)).name,
                            "abs_path": str(als_path),
                            "mime": "application/octet-stream",
                        }
                    )
                print(
                    f"[reroll] wrote Live Set → {als_info.get('als_path')}",
                    flush=True,
                )
        except Exception as exc:
            als_info = {"ok": False, "error": str(exc)}
            errors.append(f"ALS project: {exc}")
            print(f"[reroll] ALS export failed: {exc}", flush=True)
    elif write_als and not audio_out:
        als_info = {"ok": False, "error": "no audio stems to put in Live Set"}
        errors.append("ALS project: no audio stems")

    # Refresh lists after optional ALS file entry
    audio_out = [f for f in files_out if f.get("role") == "audio"]
    midi_out = [f for f in files_out if f.get("role") == "midi"]

    manifest = {
        "ok": True,
        "name": name or label,
        "bpm": bpm,
        "key": key,
        "style": style,
        "bars": bars,
        "folder": str(folder.resolve()),
        "drop_folder": str(drop_dir.resolve()) if drop_paths else None,
        "user_library_folder": user_lib_dir,
        "als": als_info,
        "als_path": (als_info or {}).get("als_path"),
        "als_project_dir": (als_info or {}).get("project_dir"),
        "write_als": bool(write_als),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "files": files_out,
        "audio": audio_out,
        "midi": midi_out,
        "errors": errors,
        "hint": (
            "Double-click the .als in this folder to open in Live. "
            "Or drag .wav stems onto empty Session space (one track per file)."
        ),
    }
    (folder / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    (folder / "README.txt").write_text(
        "\n".join(
            [
                f"Loop export · {manifest['name']}",
                f"{int(bpm)} BPM · {key} · {style} · {bars} bars",
                "",
                "ABLETON LIVE SET (.als):",
                (
                    f"  Open: {als_info.get('als_path')}"
                    if als_info and als_info.get("ok")
                    else "  (not written — enable write_als or check errors)"
                ),
                "  Project folder includes Samples/Imported stems.",
                "",
                "OR drag stems (one track per file):",
                "  1. Explorer opens with .wav selected",
                "  2. Drop on EMPTY space in Session/Arrangement",
                "     (below tracks — NOT onto one track)",
                "",
                "Also: Live browser → User Library → Samples → Reroll",
                "",
                f"Files: {len(files_out)}",
                *(f"WARN: {e}" for e in errors),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    # Keep a copy of manifest on the drop folder too
    if drop_paths:
        try:
            (drop_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )
        except OSError:
            pass
    return manifest
