# Reroll

**By Austin Russell**

Local tool to turn **your** samples + Serum libraries into inspiring loops, then hand off to Ableton.

> Your collection, infinite ideas. · Lock the keepers. Dice the rest.

**Open app → 🎲 Reroll → Listen → Lock / dice → Export → Produce in Ableton.**

Not a song finisher, not cloud AI music, not a DAW replacement.

---

## Requirements

| Piece | Version / notes |
|--------|------------------|
| **OS** | Windows (paths and Serum VST layout assume Windows) |
| **Python (app)** | 3.11+ recommended (3.14 works for the FastAPI app) |
| **Python (Serum host)** | **3.12 only** — DawDreamer does not track the latest CPython |
| **Browser** | Modern Chromium / Edge / Firefox (Web Audio) |
| **Optional: Serum** | Serum 1 and/or Serum 2 installed as VST3 for offline bounce |
| **Optional: library** | Splice samples and/or Xfer Serum preset folders (see [Library roots](#library-roots)) |

Without Serum host deps, the UI still runs: drums/samples work; synth tracks fall back to a simple JS synth.

---

## Quick start

```powershell
git clone <your-repo-url>
cd reroll
# or: cd loop_gen_project

# App dependencies
python -m pip install -r requirements.txt

# Run the server
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
```

Open **http://127.0.0.1:8000** (must be via the server — not `file://`).

First load loads **`library.db`** (SQLite) when present; otherwise scans default library roots, then saves the DB for faster next start. **Rescan** always re-walks disk and refreshes the DB.

### Optional: real Serum bounce

Install **Python 3.12**, then:

```powershell
py -3.12 -m pip install dawdreamer numpy scipy serum2-preset-loader
```

| Plugin | Default path | Presets |
|--------|----------------|---------|
| Serum 1 | `C:\Program Files\Common Files\VST3\Serum_x64.dll` | `.fxp` under Xfer Serum Presets |
| Serum 2 | `C:\Program Files\Common Files\VST3\Serum2.vst3` | `.SerumPreset` under Xfer Serum 2 Presets |

The app shells out to `py -3.12` / `Python312` for render + macros. Serum 2 may **ACCESS_VIOLATION on process exit** after a successful bounce — the backend still accepts `ok: true` JSON.

### Optional: user preferences template

Runtime prefs are written to `user_settings.json` (gitignored). To seed manually:

```powershell
copy user_settings.example.json user_settings.json
```

Defaults also work with no file present.

---

## Dependencies

### Main app (`requirements.txt`)

| Package | Role |
|---------|------|
| `fastapi` | HTTP API |
| `uvicorn[standard]` | ASGI server |
| `python-multipart` | Form uploads (future-proof) |
| `mutagen` | Sample metadata |
| `mido` | MIDI helpers / export path |

Install:

```powershell
python -m pip install -r requirements.txt
```

### Dev / tests (`requirements-dev.txt`)

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests/unit -q
```

### Serum host (Python 3.12, separate install)

```powershell
py -3.12 -m pip install dawdreamer numpy scipy serum2-preset-loader
```

Optional live Serum sync test:

```powershell
py -3.12 -m pytest tests/host -m serum -q
# or: py -3.12 host/test_serum_sync.py
```

---

## Library roots

On scan, the app always includes these defaults (typical installs):

| Kind | Path |
|------|------|
| Samples | `%USERPROFILE%\Documents\Splice\Samples\packs` |
| Serum 1 | `%USERPROFILE%\Documents\Xfer\Serum Presets\Presets` |
| Serum 2 | `%USERPROFILE%\Documents\Xfer\Serum 2 Presets\Presets` |

**Extra folders** (Google Drive, curated dumps, etc.) go in `user_settings.json` as `sampleRoots` / `serumRoots`, or edit them under **Library** in the UI (Save & Scan).

```json
"serumRoots": ["G:\\Other computers\\Snowy\\music\\serum presets"]
```

Remote / File Stream paths work if Windows can open the files (online-only placeholders may fail or be slow). Rescan anytime from **Library** or `POST /api/scan`. Catalog loads from `library.db` on startup when present; Rescan re-walks disk.

---

## Using the app

1. Set **BPM**, **key**, **style** (session controls).
2. **Reroll** — fills unlocked tracks from your library.
3. **Lock** keepers; **dice** (🔀 per track) or **Reroll** the rest.
4. **Play** (or **Space**) — loops forever; button toggles stop.
5. Serum tracks: **M** opens MIDI editor (stackable); length toolbar + drag to resize notes; macros when the host can load the preset.
6. Sample **loops** (hats, beds, etc.) warp to session BPM when the filename has a tempo tag (e.g. `_140_`) and re-lock to the kick cycle.
7. **Export for Ableton** — flat stems + optional **`.als` Live Set** (checkbox) + in-app drag tray. Also mirrors to `exports/ABLETON_DROP/` and Live **User Library → Samples → Reroll**.

### Transport status bar

| Color | Meaning |
|-------|---------|
| Grey | Idle |
| Green (breathing) | Playing |
| Yellow | Working (load samples, Serum bounce, reroll, dice) |

### Keyboard

| Shortcut | Action |
|----------|--------|
| **Space** | Play / stop (when not typing in a field) |
| **Ctrl+Z** | Undo |
| **Ctrl+Y** / **Ctrl+Shift+Z** | Redo |

---

## Project layout

```text
reroll/   (or loop_gen_project/)
  README.md
  requirements.txt          # main app
  requirements-dev.txt      # + pytest
  user_settings.example.json
  backend/                  # FastAPI (scan, reroll, settings, Serum proxy)
  frontend/                 # UI + Web Audio + MIDI editor
  host/                     # Python 3.12 DawDreamer CLI + worker + cache/
  exports/                  # Ableton handoff (gitignored contents)
  saves/                    # Named loop JSON (gitignored contents)
  tests/                    # unit (+ optional host/serum)
  docs/
  spikes/                   # experiments (see spikes/README.md)
```

### Architecture

```text
Browser (frontend/)
      ↕  HTTP
FastAPI (backend/) — catalog, reroll, options, export open
      │
In-memory catalog (scan of local disks)
      ↕  subprocess
Host CLI / worker (Python 3.12 + DawDreamer)
      ├── Serum 1 (.fxp) or Serum 2 (.SerumPreset)
      ├── MIDI from monophonic grids
      └── bounce WAV → host/cache → browser
```

---

## Development

```powershell
# App with auto-reload
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload

# Unit tests (no Serum required)
python -m pytest tests/unit -q
```

If port **8000** is stuck, stop leftover `python`/`uvicorn` processes or pick another port:

```powershell
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8001 --reload
```

### Useful APIs

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/health` | Liveness |
| `GET` | `/api/library` | Catalog summary |
| `POST` | `/api/scan` | Rescan library roots |
| `POST` | `/api/generate` | Reroll / fill tracks |
| `POST` | `/api/reroll` | Dice one track |
| `POST` | `/api/serum/render` | Offline Serum bounce |
| `POST` | `/api/serum/macros` | Macro names/values |
| `POST` | `/api/serum/open` | Launch plugin UI |
| `GET`/`POST` | `/api/settings` | User prefs |
| `POST` | `/api/export` | Export session → stems + MIDI (+ optional `.als`) |
| `POST` | `/api/export/open` | Open `exports/` (or a subfolder) in Explorer |

### Export → Ableton

```text
exports/
  20260810_153012_techno-f-minor-140bpm/
    01_kick_….wav
    02_bass_….wav
    03_bass_…_midi.mid
    manifest.json
    My Loop Project/           # when “Write .als Live Set” is on
      My Loop.als
      Ableton Project Info/
      Samples/Imported/…
  ABLETON_DROP/                # always the latest export (flat)
```

**Supported handoff:** drag flat stems onto empty Session/Arrangement space (one track per file), or use Live browser → **User Library → Samples → Reroll**.

**`.als` Live Set (experimental / paused):** code can write a project folder, but **Live still hard-crashes on open** on this machine’s Live 12 builds. Prefer **stems only** (uncheck Write .als). Full attempt log: [`docs/ALS_EXPORT_STATUS.md`](docs/ALS_EXPORT_STATUS.md).

### Library DB

- File: `library.db` (gitignored, project root)
- Written on first scan / every **Rescan**
- Loaded on startup when non-empty

---

## What works today

| Area | Notes |
|------|--------|
| Dynamic tracks | Add / delete; stack any number |
| Reroll / dice | Unlocked tracks only; Reroll auto-plays |
| **Style lean** | Soft pack/path weights; suggestions ranked from *your* pack names; No preference = random |
| Serum 1 / 2 filter | Options + per-track type (BASS, LEAD, …) |
| MIDI | Monophonic 16-step grids; note length + edge drag |
| Macros | S1 mapped renames; S2 names from `.SerumPreset` file |
| Sample loops | Tempo match via `playbackRate` (pitch shifts with BPM) + kick-cycle re-lock — see [sample warp notes](docs/SAMPLE_WARP.md) |
| Serum stems | Offline bounce; re-trigger each loop cycle |
| **Export** | Audio + MIDI stems for Ableton (supported) |
| **`.als` Live Set** | **Paused** — writer exists; Live open still unreliable (see `docs/ALS_EXPORT_STATUS.md`) |
| **Library DB** | SQLite cache for fast restart |
| JS synth fallback | If host missing or bounce fails |
| Mute / solo / lock | Live while playing |
| Undo / redo | Ctrl+Z / Ctrl+Y |

---

## Planned / gaps

### Next (higher impact)

| Feature | Notes |
|---------|--------|
| **Writing-night hook** | 4-bar progression + dice-lead on `/` so Serum isn’t a tiled 1-bar wallpaper. Spec: [`docs/WRITING_NIGHT_HOOK.md`](docs/WRITING_NIGHT_HOOK.md). `/arrange` is deferred ([`docs/SUBTRACTIVE_ARRANGER.md`](docs/SUBTRACTIVE_ARRANGER.md)). |
| **Pitch-preserving sample warp** | Long loops (8-bar beds, etc.) must match session BPM **without** chipmunk pitch. Homemade WSOLA **failed** (drone / single-tone on melodic loops). Next: Rubber Band or server-side quality stretch — full notes in [`docs/SAMPLE_WARP.md`](docs/SAMPLE_WARP.md) |
| **“More like this”** | Seed similar sounds from a locked track |
| **Richer library browser** | Search / filter / preview beyond role counts |

### Nice to have

| Feature | Notes |
|---------|--------|
| **User role overrides** | Tag roles in DB instead of filename heuristics only |
| **Incremental rescan** | mtime / hash delta instead of full re-walk |
| **Energy control** | First-class session energy (early requirements) |
| **Key-aware sample pick** | Filter/pool by detected or tagged key (filename key → transpose already partial) |
| **Warp markers / multi-bar clip length** | After solid global warp: optional 4- vs 8-bar loop braces |
| **Richer MIDI** | Covered by the writing-night hook spec (64-step grids, pad voicings) |
| **Serum param editing** | Beyond macros + offline bounce |
| **Named saves polish** | Session browser UX for `saves/` |
| **Stale path recovery** | Clear errors when DB paths move off disk |
| **Reliable `.als` open in Live** | Stems work; `.als` generation paused (see `docs/ALS_EXPORT_STATUS.md`) |
| **MIDI tracks in `.als`** | Would be audio-only in set; MIDI still as `.mid` files |

### Non-goals for now

Full song arrangement · cloud libraries · shipping Serum · replacing Ableton · chat-style AI production

---

## Product principle

1. Set BPM / key / style  
2. **Reroll** from *your* library  
3. Lock keepers, dice the rest  
4. Edit Serum MIDI  
5. Preview fast  
6. Export → Ableton  

Optimize for **time-to-inspiring-start**, not finishing the track in-app.

> I didn’t make this track for you. I made it much easier for you to start making it.
