# Ableton `.als` export — status (paused)

**Date:** 2026-08-11  
**Status:** **Paused / not reliable.** Live still hard-crashes on open (“A serious program error has occurred”).  
**Recommendation:** Export **stems + MIDI only** (disable “Write .als Live Set”). Drag `.wav` files into Live. Revisit `.als` later with a golden file from the user’s Live version.

---

## Goal

Ship a double-clickable Ableton Live Set (`.als` + `Samples/Imported/`) from Reroll so stems appear as tracks at session BPM, without drag-and-drop.

`.als` = gzip-compressed Ableton XML. Live is extremely strict about schema, list indices, and global “pointee” IDs.

---

## What works today

| Piece | Status |
|--------|--------|
| Flat stem export (`.wav` / `.mid` under `exports/<stamp>_…/`) | **Works** |
| Explorer select / ABLETON_DROP / User Library mirror | **Works** |
| Export API + UI checkbox `write_als` | **Works** (writes a file; Live may not open it) |
| Unit tests (`tests/unit/test_export_als.py`) | **Pass** (structure checks only — **cannot** detect Live crashes) |
| Gzip XML parse, tempo, multi-track clone, sample paths | **OK in isolation** |

---

## What fails

| Symptom in Live | When observed |
|-----------------|---------------|
| `unexpected value for int node: major` | Live 12.2 scale schema: `ScaleInformation/Name` must be int index, not `"Major"` |
| `track grouping corrupt` | Template track had `TrackGroupId=124` but parent `GroupTrack` was removed |
| `non-unique pointee IDs` (+ optional repair dialog) | Cloning tracks duplicated `AutomationTarget` / `ModulationTarget` / related Ids |
| **`A serious program error has occurred`** (no repair prompt) | **Still happening** on latest build after all of the above fixes — root cause **unknown** |

Saying “Yes” to repair after pointee errors was followed by the same critical crash (expected: repair cannot fix a set we generated incorrectly).

---

## Current code state (at pause)

| Path | Role |
|------|------|
| `backend/export_als.py` | Writer: load template, clone tracks, session clips, path rewrites, strip returns/sends, scale/group normalize, **global pointee uniquify**, optional arrangement via `REROLL_ALS_ARRANGEMENT=1` (**default off**) |
| `backend/templates/live_set_template.xml` | Template rebuilt from Ableton **DefaultLiveSet.als** + Live **12.2.6** clip shape (`scripts/build_als_template_from_default.py`) |
| `backend/export_loop.py` | Calls `write_als_project` when `write_als=True` |
| `frontend` | “Write .als Live Set” checkbox; opens Explorer on `.als` after export |

**Arrangement clips:** disabled by default (session scene 1 only). Re-enable only with env `REROLL_ALS_ARRANGEMENT=1` (experimental; historically crash-prone).

**Smoke folder:** `exports/_open_me_in_live/` may contain a last generated probe set — treat as disposable.

---

## Approaches tried

### 1. Hand-maintained / sanitized template
- Started from an older sanitized Live set XML.
- Stripped Live-12-only classes (`ExpressionLanes`, `MidiEditorLaneModel`, …).
- **Failed:** wrong scale types, inventing fields, drift from real Live 12.2 XML.

### 2. Fix scale fields
- Live 12.2:  
  `<ScaleInformation><Root Value="0"/><Name Value="0"/></ScaleInformation>`  
  not `RootNote` + `Name="Major"`.
- **Helped** that specific parse error; **did not** stop hard crashes.

### 3. Template from user’s real Live 12.2.6 crash dump
- Extracted one `AudioTrack` + clip from a real project.
- **Failed:** track still belonged to a **group** (`TrackGroupId=124`); routing `AudioOut/GroupTrack`; leftover **plugins/automation** → grouping corrupt / unstable.

### 4. Official Ableton DefaultLiveSet.als
- Source:  
  `C:\ProgramData\Ableton\.Live 12 Suite_updated\Resources\Builtin\Templates\DefaultLiveSet.als`
- Clip body from user Live 12.2.6 (avoid mixing 12.3-only clip into older claims).
- Stripped MIDI/returns, one scene, zero sends, `TrackGroupId=-1`, route to Master.
- **Best skeleton so far**, still not openable reliably in user’s Live.

### 5. ClipSlot / list index discipline
- **Bug:** renumbered *every* `Id=` including `ClipSlot` / `WarpMarker` → slots no longer matched scenes.
- **Fix:** treat `ClipSlot` / `Scene` / `WarpMarker` as **list indices** (0..n-1 only).
- **Necessary**, insufficient alone.

### 6. Arrangement timeline clips
- Injected `AudioClip` under `MainSequencer/Sample/ArrangerAutomation/Events`.
- Tried unwarped (factory-like) and warped (matching Sec/Beat markers).
- Invented `ArrangementClipsListWrapper` / `TakeLanesListWrapper` / `SourceHint` at times — **real factory FileRefs have no SourceHint**.
- **Paused:** arrangement inject **off** by default after repeated serious errors.

### 7. Global pointee uniquify (latest)
- Cloning tracks duplicated large Ids on `Pointee`, `AutomationTarget`, `ModulationTarget`, `*ModulationTarget`, etc.
- Live can report **non-unique pointee IDs**.
- Final pass: clear automation envelopes; reassign all non-list-local `Id=` uniquely; set `NextPointeeId`.
- Unit tests assert unique Pointees / AutomationTargets.
- **Still:** user reports **serious error only** (no repair dialog) → remaining bug is **not** fully explained by tests.

---

## Likely remaining causes (unverified)

Live does not give a stack trace. Any of these may still be wrong:

1. **Schema mix** — DefaultLiveSet (12.1d1 lineage) + 12.2.6 header/clip + ElementTree rewrite order.
2. **MainTrack / PreHearTrack** state after stripping returns/sends/devices (hidden refs).
3. **Which `Id`s are pointee-space vs list-local** — exclusion list may be incomplete or too aggressive.
4. **Nested `ClipSlot` / `ClipSlot` / `Value` shape** after session normalize.
5. **SampleRef / warp / duration** inconsistent with file on disk.
6. **ElementTree serialization** (empty elements, attribute order, encoding) — usually OK, not proven.
7. **Something only Live validates at load** that pure XML checks never see.

**Important:** pytest **cannot** open Live. Green tests ≠ openable `.als`.

---

## What we did *not* try (next time)

1. **Golden-file workflow:** User saves empty set in *their* Live build → use that exact file as template; only rewrite paths/tempo/clips with minimal edits (prefer binary gzip copy + surgical XML edits).
2. **Diff against a set Live just saved** after manually importing one stem (ground truth).
3. **Single-track minimal ALS** (one clip, no clone loop) to isolate multi-track Id issues.
4. **Third-party writers** (e.g. community ALS libraries) for a known-good baseline.
5. **Live’s own “Export” / collect-and-save** round-trip test on our output.
6. **Arrangement** only after session-only opens 100%.

---

## Practical handoff (use this now)

1. In Reroll: **uncheck “Write .als Live Set”** (or ignore failed `.als`).
2. **Export for Ableton** → use flat `.wav` stems.
3. In Live: drop stems on empty Session/Arrangement area (one track per file), or import from `exports/ABLETON_DROP` / User Library → Samples → Reroll.

---

## Key files / commands

```text
backend/export_als.py
backend/templates/live_set_template.xml
scripts/build_als_template_from_default.py   # rebuild template from factory DefaultLiveSet
tests/unit/test_export_als.py
docs/ALS_EXPORT_STATUS.md                    # this file
```

```bash
# unit tests only
python -m pytest tests/unit/test_export_als.py -q

# rebuild template (requires Ableton install paths on this machine)
python scripts/build_als_template_from_default.py

# experimental arrangement clips
set REROLL_ALS_ARRANGEMENT=1
```

---

## Decision

**Stop iterating on `.als` open-in-Live until** there is a **user-provided golden `.als`** that opens on their exact Live version, or a dedicated spike that produces a **single-track** set proven to open before multi-track is re-enabled.

Stems export remains the supported Ableton handoff path.
