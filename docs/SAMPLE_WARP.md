# Sample warp (pitch-preserving tempo match)

**Status:** not shipped — two attempts failed; need a real solution for long loops  
**Need:** Warp multi-bar samples (e.g. 8-bar synth loops tagged `_135_`) to session BPM **without** chipmunk / slowdown pitch.

---

## Why we need it

Long phrase samples (lead/bass beds, hat loops, construction kits) often include a native BPM in the name:

```text
ZEN_IMP_135_synth_loop_sos_Dm.wav  →  14.22 s  =  exactly 8 bars @ 135 BPM
```

Session may be 128–140 BPM. Today we match tempo with Web Audio **`playbackRate`**, which **couples tempo and pitch**. That is wrong for melodic loops (and for anything that should stay in key after BPM changes).

Key transpose from filename tags (e.g. `_Dm_`) is separate and still useful; it currently also multiplies `playbackRate`.

---

## What we ship today

| Behavior | Implementation |
|----------|----------------|
| Phrase beds | `playbackRate = sessionBpm / nativeBpm` (and key factor) |
| Kick-lock | Restart beds every transport cycle |
| Export sample stems | Same cheap resample stretch in `backend/render_sample_loop.py` |
| Short one-shots | Usually fine (no / little stretch) |

**Tradeoff:** loops stay recognizable; BPM changes pitch-shift.

---

## Attempt history (do not repeat blindly)

### 1) Homemade WSOLA on the main thread (frontend + numpy)

- Offline grain stretch, play at rate 1.
- **Failed UX:** BPM scrub re-stretched every input → lag, glitches, audio dropouts.
- Reverted.

### 2) Same WSOLA in a Web Worker + debounced re-warp

- Files briefly: `frontend/warp-worker.js`, `backend/warp.py`, worker URL `/warp-worker.js`.
- **Failed sound:** short stabs OK; **long melodic loops became a continuous drone / single-tone “GAHHH”.**
- Classic failure mode: adaptive grain search locks onto a harmonic period and OLA smears the loop into a steady tone (especially dense synth material).
- Fully removed again; playback restored to `playbackRate`.

**Do not reintroduce naive WSOLA/OLA “time stretch” for musical loops without listening tests on real Splice multi-bar beds.**

---

## Requirements for a real fix

1. **Pitch independent of tempo** — match Ableton “Warp” / Beats or Complex Pro intent for our case (we mainly need constant pitch + tempo scale, not full clip warp markers v1).
2. **Works on 4–16 bar stereo loops** at 44.1/48 kHz, not only short one-shots.
3. **BPM change:** re-warp must not freeze UI or click/glitch; debounce + swap on boundary is fine.
4. **Session key:** optional pitch shift of labeled roots without undoing tempo match (order: tempo-warp then pitch-shift, or a library that does both).
5. **Export parity:** offline stems must use the same algorithm as preview.
6. **Latency budget:** first play can wait a bit; live BPM scrub can lag ~200–400 ms after settle.

---

## Future approaches (recommended order)

### A. **Rubber Band Library** (best first bet)

- Industry-grade pitch-preserving stretch (same family Ableton-ish tools use under the hood elsewhere).
- **Python:** `pyrubberband` (needs [Rubber Band](https://breakfastquay.com/rubberband/) CLI/lib installed) or bindings.
- **Native:** link Rubber Band into a small host CLI next to the Serum worker.
- **Browser:** WASM build of Rubber Band (exists in community ports) or always warp on server and stream WAV.

**Pros:** quality on long loops. **Cons:** dependency / install story on Windows.

### B. **Server-side warp API**

```text
POST /api/sample/warp  { path, native_bpm, session_bpm, semitones? }
→ WAV or float PCM URL (cached by path|bpm|key)
```

- Preview and export both call this (or export reuses the same function).
- Cache under `host/cache/` or `exports/.warp-cache/`.
- Frontend always plays **rate = 1** after load.

**Pros:** one implementation; no main-thread audio CPU. **Cons:** network round-trip; need path allowlist (same as `/api/audio`).

### C. **SoundTouch / libsamplerate-style only for drums**

- Drums tolerate more artifacts; melodic loops still need A or B.

### D. **Phase vocoder (librosa / scipy STFT)**

- `librosa.effects.time_stretch` / `pitch_shift` — better than WSOLA for many sources, still not Rubber Band quality; heavy for live, OK offline.

### E. **Don’t stretch in the browser at all for v1**

- Only warp on **export** and for **Serum-style offline beds**; preview uses rate (document the pitch shift) until A lands.

### F. **Warp markers / clip start (later)**

- Ableton also needs transient markers and loop braces for odd lengths.
- v1 can assume: filename BPM + duration ≈ N bars; stretch whole clip uniformly (Beats/Complex “global” rate).

---

## Suggested implementation plan (next time)

1. Spike Rubber Band (or `pyrubberband`) on one known file:  
   `ZEN_IMP_135_synth_loop_sos_Dm.wav` → 140 BPM, listen A/B vs original.
2. If good, wrap in `backend/warp.py` using the **library**, not homemade grains.
3. Add `POST /api/sample/warp` + disk cache.
4. Frontend: phrase beds load warped buffer once; BPM change debounced → new buffer → swap at cycle boundary; **never** use adaptive WSOLA in JS.
5. Point `render_sample_loop` at the same warp function.
6. Keep `playbackRate` as **fallback** when native BPM missing or warp fails.

---

## Related code (current)

| Area | Location |
|------|----------|
| Phrase BPM rate | `frontend/app.js` — `phrasePlaybackFor`, `sampleBpmWarpOpts`, `retuneWarpedSources` |
| Export stretch | `backend/render_sample_loop.py` — `_time_stretch` (linear resample) |
| Key from name | `backend/midi_util.py` — `parse_key_from_name`, `transpose_semitones_from_name` |
| Key in UI | `frontend/app.js` — `parseKeyFromName`, `sampleKeyTransposeSemitones` |

---

## Decision log

| Date | Decision |
|------|----------|
| 2026-08 | Need pitch-preserving warp for long samples. |
| 2026-08 | Homemade WSOLA (main thread + worker) **rejected** — drone artifacts + UX pain. |
| 2026-08 | Stay on `playbackRate` until Rubber Band (or equivalent) is wired. |
