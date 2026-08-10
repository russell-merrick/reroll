# Requirements — Personal AI Loop Generator

**Status:** draft for V0  
**Scope:** local Windows tool, Ableton + Splice workflow  
**Deferred:** database, AI classification, Ableton project generation, cloud

---

## 1. Product goal

Get from a blank idea to an **inspiring 8-bar electronic loop** as fast as possible, using **only local assets** (user samples + Serum presets), then hand off to Ableton.

Primary metric: **time to first usable starting point**.

Non-goals (V0–V0.6):

- Finished songs
- Replacing Ableton
- Chat-style AI production
- Uploading libraries

---

## 2. What we found on this machine

| Source | Path | Notes |
|--------|------|--------|
| **Splice samples** | `C:\Users\russe\Documents\Splice\Samples\packs` | **313 pack folders**, **~508 audio files**, ~1 GB. Selective downloads (often 1–16 files per pack), not full packs. Heavy techno / tech house / melodic techno bias. |
| **Splice instruments** | `C:\Users\russe\Splice\INSTRUMENT` | LABS packs etc. (secondary). |
| **Serum presets** | `C:\Users\russe\Documents\Xfer\Serum Presets\Presets` | **~472 `.fxp`** across Bass, Leads, Pads, Plucked, Seq, FX, User (3), Splice (11). Factory-style layout already role-friendly. |
| **Ableton User Library samples** | `...\Documents\Ableton\User Library\Samples` | **Empty.** Good candidate as *destination* if we reorganize. |
| **Ableton factory / suite** | `C:\ProgramData\Ableton\...` | Thousands of stock files. **Do not** treat as personal library by default. |
| **Downloads** | `...\Downloads`, `...\Downloads\Samples` | Mix of Beatport full tracks + a few one-shots (e.g. Oliver kick). Not a clean library. |
| **G:** | Google Drive mirror | Nearly full; not primary sample storage. |
| **D:/E:/F:** | — | Not present. |

### Filename heuristics (Splice on disk today)

Rough hits in names (overlapping): kick ~61, snare ~42, clap ~27, hat/hihat ~68, bass ~29, fx ~78, vocal ~75, loop ~119, synth ~73, lead ~21.

Enough to bootstrap a **random role picker** without a DB — if we also use **folder names** inside packs (`One_Shots\Snares`, `HiHat_Loops`, etc.).

---

## 3. Functional requirements (phased)

### V0.1 — Library awareness (in memory, no DB)

| ID | Requirement |
|----|-------------|
| L1 | User can set one or more **root folders** to scan (default: Splice packs + Serum Presets). |
| L2 | Recursively discover audio: `.wav`, `.aif`, `.aiff` (optional: `.flac`). |
| L3 | Recursively discover Serum: `.fxp` under Serum Presets. |
| L4 | For each file, capture: absolute path, name, extension, size, parent folders. |
| L5 | Assign a **best-effort role** from path + filename (kick, snare/clap, hat, perc, bass, lead, pad, fx, vocal, loop, unknown). |
| L6 | UI shows scan summary: counts per role, list/browse samples. |
| L7 | Rescan replaces in-memory catalog (no persistence yet). |

**Success:** App knows what *your* samples and Serum presets are on this HDD.

### V0.2 — Session controls + random fill

| ID | Requirement |
|----|-------------|
| G1 | Controls: BPM, key, style (free text or small preset list), optional energy. |
| G2 | **Generate** fills slots: Kick, Clap/Snare, Hats, Perc, Bass (Serum or sample), Lead (Serum or sample), optional FX. |
| G3 | Empty roles allowed (sparse loops). |
| G4 | Show chosen asset name + path for each slot. |

### V0.3 — Lock / dice

| ID | Requirement |
|----|-------------|
| R1 | Per-slot **Lock** (keep on regenerate). |
| R2 | Per-slot **Dice** (reroll that slot only). |
| R3 | Global Generate only rerolls unlocked slots. |

### V0.4 — Preview + export (Ableton handoff)

| ID | Requirement |
|----|-------------|
| E1 | Export folder: `audio/` one-shots or rendered stems + `midi/` when available. |
| E2 | Open export folder in Explorer (drag into Ableton). |
| E3 | Preview: at minimum play selected one-shots in browser; full loop bounce later. |

### Explicitly out of scope for early V0

- SQLite / any durable index (re-add when catalog is large or slow)
- Semantic search / embeddings
- Parsing Serum preset DSP parameters
- Writing `.als` projects
- Using Live Suite factory content as default pool

---

## 4. Non-functional requirements

| ID | Requirement |
|----|-------------|
| N1 | Local-only; no upload of sample libraries. |
| N2 | Windows-first; UI at `http://localhost:8000`. |
| N3 | Generate path should feel instant once catalog is in memory (&lt; ~200 ms target for random pick). |
| N4 | Scan of ~500–5k files should complete in seconds, not minutes. |
| N5 | Fail soft: missing files after move → clear error on that slot, rest still work. |

---

## 5. Default library roots (this machine)

```text
Samples:
  C:\Users\russe\Documents\Splice\Samples\packs

Serum:
  C:\Users\russe\Documents\Xfer\Serum Presets\Presets
```

User may add more roots later (e.g. a reorganized `D:\Library` or Ableton User Library).

---

## 6. Stack (V0)

```text
Python + FastAPI
  → in-memory catalog (list/dict)
  → static / simple web UI
  → localhost
```

See `requirements.txt` at repo root. **No database dependency.**

---

## 7. UI requirements (see also `frontend/`)

Must support the core loop:

> Generate → hear/see result → lock what works → generate again → export to Ableton

Minimum chrome:

- Session bar: BPM, Key, Style, Generate
- Slot list: role, asset name, lock, dice
- Preview + Export / Open folder
- Library panel: roots, scan, role counts

Visual style: dark, dense, studio-tool — not a marketing site. Optimize for **one-handed iteration**, not feature discovery.
