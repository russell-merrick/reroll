# Austin Russell Loop Machine

Local tool to turn **your** samples + Serum libraries into inspiring loops, then hand off to Ableton.

> Your collection, infinite ideas.

Open app → Generate → Listen → Lock / dice → Export → Produce in Ableton.

**Not** a song finisher, not cloud AI music, not a DAW replacement.

---

## Status (for continuing in a new chat)

Use this section as the handoff. Project path: `C:\Users\russe\Desktop\loop_gen_project`.

### Run

```powershell
cd C:\Users\russe\Desktop\loop_gen_project
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
```

Open **http://127.0.0.1:8000** (not `file://`).

If port 8000 is stuck on an old process, kill uvicorn/python orphans or use another port.

### Tests

```powershell
cd C:\Users\russe\Desktop\loop_gen_project
python -m pip install -r requirements-dev.txt
python -m pytest tests/unit -q
```

Optional live Serum sync (needs **Python 3.12** + DawDreamer + local presets):

```powershell
py -3.12 -m pip install dawdreamer numpy scipy serum2-preset-loader pytest
py -3.12 -m pytest tests/host -m serum -q
# or: py -3.12 host/test_serum_sync.py
```

### Host deps (Serum bounce)

```powershell
py -3.12 -m pip install dawdreamer numpy scipy serum2-preset-loader
```

| Plugin | Path | Presets |
|--------|------|---------|
| Serum 1 | `C:\Program Files\Common Files\VST3\Serum_x64.dll` | `.fxp` via `load_preset` |
| Serum 2 | `C:\Program Files\Common Files\VST3\Serum2.vst3` | `.SerumPreset` via `serum2-preset-loader` → `load_state` |

Serum 2 host process often **ACCESS_VIOLATIONs on exit** after printing JSON — backend accepts `ok: true` stdout even when return code is bad.

### Library scan roots

- `Documents\Splice\Samples\packs`
- `Documents\Xfer\Serum Presets\Presets` (Serum 1)
- `Documents\Xfer\Serum 2 Presets\Presets` (Serum 2)

Typical counts after scan: ~500 samples, ~900+ S1, ~700+ S2 (in-memory only).

### What works now

| Area | Notes |
|------|--------|
| **Dynamic tracks** | Add (`+` + type), delete (🗑), stack any number |
| **Generate / dice / shuffle** | Fills unlocked tracks; payload uses `tracks[]` |
| **Serum engine filter** | Per Serum track: **1** / **2** / **\*** next to M (strict; no S2→S1 fallback) |
| **Serum type filter** | Dropdown on Serum tracks (BASS, LEAD, ARP, …) |
| **MIDI** | Monophonic 16-step grids; **M** opens editor; **multiple editors stack** |
| **Macros** | In MIDI panel; S1 mapped renames only; S2 shows Macro 1–8 |
| **Play** | Toggle (Space); loops forever; no separate Stop button |
| **Sample loops** | Phrase beds; BPM from filename (e.g. `_155_`) warped to session BPM |
| **Serum audio** | Offline bounce via host → stem; **re-triggers each cycle** on transport (kick-locked); latency trim + exact bar length |
| **JS synth fallback** | If host/render fails |
| **Options** | Inline section above loop (not modal): filter out risers/builds/downlifters/rolls |
| **Export folder** | `exports/` with `audio/` + `midi/`; **Open export folder** opens Explorer |
| **Mute / solo / lock** | Live mute/solo; lock keeps sound on generate |

### Key APIs

- `POST /api/generate` — `tracks`, `filter_risers`, etc.
- `POST /api/reroll` — `slot`, `serum_engine`, `serum_type`, `filter_risers`
- `POST /api/serum/render` · `POST /api/serum/macros` · `POST /api/serum/open`
- `POST /api/export/open` · `GET /api/export/path`
- `GET /api/library` · `POST /api/scan`

### Layout

```text
loop_gen_project/
  README.md
  requirements.txt
  backend/          # FastAPI (app can be 3.14)
  frontend/         # UI + Web Audio + MIDI
  host/             # Python 3.12 DawDreamer renderer (cli_render, cache/)
  exports/          # Ableton handoff folder
  spikes/
  docs/
```

### Not done / next

- Full export of stems + `.mid` into `exports/`
- SQLite / durable catalog
- Style-based pack filtering
- Ableton project generation
- AI tags / “More like this”
- Splice pack artwork (not available locally; waveforms would be the offline path)

### Explicit non-goals (for now)

- Full song arrangement  
- Cloud sample libraries  
- Shipping or cracking Serum  

---

## Product goals

1. Set BPM / key / style  
2. **Generate** from *your* library  
3. Lock keepers, dice the rest  
4. Edit Serum MIDI (**M**, stackable)  
5. Preview fast (Space)  
6. Export → Ableton  

Optimize for **time-to-inspiring-start**, not finishing the track in-app.

---

## Architecture

```text
Browser UI (frontend/)
      ↕
FastAPI (backend/) — scan, generate, options, export open
      │
In-memory catalog
      ↕
Host CLI (Python 3.12 + DawDreamer) on each Serum render/macros
      ├── Serum 1 (.fxp) or Serum 2 (.SerumPreset)
      ├── MIDI from patterns
      └── bounce WAV → host/cache → browser
```

---

## Critical principle

> **I didn’t make this track for you. I made it much easier for you to start making it.**
