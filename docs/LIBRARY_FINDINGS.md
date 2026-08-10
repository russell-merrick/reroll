# Library findings & reorg options

Scanned on this machine for Ableton + Splice + Serum paths.

---

## What exists today

### Splice (primary sample pool)

```text
C:\Users\russe\Documents\Splice\Samples\packs\
```

| Fact | Value |
|------|--------|
| Pack folders | **313** |
| Audio files on disk | **~508** (~1 GB) |
| Pattern | Selective Splice downloads — often **1–16 files per pack**, not full packs |
| Genre tilt | Strong **Techno / Melodic Techno / Tech House / Hard Techno**; also Trance, vocals, FX, KSHMR drums |

**Internal layout is inconsistent** (normal for Splice):

- Some packs: `One_Shots\Snares\Hard_Snares\…`
- Some: `HiHat_Loops\…`
- Some: flat `loops\drum_loops\…`
- Filenames often encode role + BPM + key (`SO_DN_136_synth_…_Amin.wav`)

That is **good enough for heuristics**, bad for “always perfect” classification without ML later.

### Serum

```text
C:\Users\russe\Documents\Xfer\Serum Presets\Presets\
```

| Category | ~Count |
|----------|--------|
| Bass | 38 |
| Bass (Hard) | 54 |
| Leads | 71 |
| Pads | 49 |
| Plucked | 32 |
| Seq | 80 |
| Synth | 61 |
| FX | 52 |
| Misc | 21 |
| Splice | 11 |
| User | 3 |
| **Total** | **~472** |

Serum is already **role-sorted by folder**. Best library we have for musical slots.

### Ableton

| Location | State |
|----------|--------|
| `Documents\Ableton\User Library\Samples` | **Empty** |
| Factory Packs / Suite under ProgramData | Large stock content — **not** your personal Splice taste |
| Recent `.als` projects under Documents\Ableton | Essentially none found (besides pack internals) |

You produce in Live, but **collected one-shots live in Splice’s tree**, not in User Library.

### Other

- `Downloads` / `Downloads\Samples`: full tracks + a few one-shots — noisy for a generator.
- **G:** Google Drive, ~20 GB free — not a sample vault.
- **No D:/E:/F:** on this machine right now.

---

## Implications for the app

1. **Default scan roots are clear** (Splice packs + Serum Presets).
2. **~500 samples is small** — in-memory catalog is fine; DB can wait.
3. **Quality > quantity risk:** many packs are thin (1–2 files). Generator will feel repetitive until you download more one-shots *or* reorganize/curate a “production pool.”
4. **Loops vs one-shots:** ~119 files look like loops from names. V0 should tag `loop` vs `one_shot` and prefer one-shots for kick/clap slots.
5. **Serum is ready** for bass/lead/pluck/pad roles without reorg.

---

## Reorganize — should you?

You don’t *have* to reorganize for V0. The scanner can walk Splice as-is.

Reorg pays off when you want:

- Faster mental browsing in Explorer + Ableton
- Cleaner role buckets for random pick
- A “trusted” pool (only sounds you actually use)
- Room to grow beyond Splice’s pack maze

### Option A — Don’t reorg (recommended to start)

- Point the app at Splice + Serum paths.
- Classify with **path + filename rules**.
- Curate by **downloading more Splice one-shots** into existing packs when roles feel thin (especially kicks/claps/hats).

**Pros:** zero file moving, Splice app stays happy.  
**Cons:** messy paths forever; weak roles stay weak.

### Option B — Shadow library (recommended if reorg)

Keep Splice downloads where they are. Build a **second tree** the app (and you) prefer:

```text
C:\Users\russe\Documents\Ableton\User Library\Samples\LoopGen\
  01_Kick\
  02_Snare_Clap\
  03_Hats\
  04_Perc\
  05_Bass_OneShots\
  06_Synth_OneShots\
  07_FX\
  08_Vocals\
  09_Loops\          # optional; separate from one-shots
  _inbox\            # drop new Splice grabs here before sorting
```

- **Copy** (not move) favorites from Splice into role folders.
- App scans `LoopGen\` as primary; Splice as optional “deep” pool.
- Ableton browser also sees the same structure under User Library.

**Pros:** clean roles, Ableton-friendly, Splice intact.  
**Cons:** some disk duplication (~1 GB today is cheap).

### Option C — Full flatten / move out of Splice

Move everything into a custom tree and stop using Splice’s folder layout.

**Pros:** one source of truth.  
**Cons:** Splice desktop may re-download or get confused; more maintenance. **Not recommended** unless you leave Splice’s sample manager behind.

### Option D — Tag in place (later)

Keep files put; store role overrides in a small JSON/DB when we add persistence.

**Pros:** no file moves.  
**Cons:** tags live only in the app until then.

---

## Practical curation tips (Ableton + Splice)

1. **Prefer one-shots for drum slots** — full drum loops fight the generator’s own patterns.
2. **Grow the thin roles first:** kicks, claps/snares, closed hats (you have some; more variety helps Generate feel fresh).
3. **Ignore suite factory** unless you explicitly want “generic Live” sounds.
4. **Serum User folder** is almost empty (3 presets) — when you design keepers, save there so “my sound” is distinct from factory.
5. If you add an external drive later (`D:\Samples`), use Option B layout there and set it as the primary root.

---

## Suggested decision for this project

| Phase | Library strategy |
|-------|------------------|
| **Now** | Scan Splice packs + Serum as-is (Option A). |
| **When Generate feels repetitive** | Start Option B: copy 50–100 favorite one-shots into `User Library\Samples\LoopGen\`. |
| **Later** | App primary root = LoopGen; Splice = optional expanded pool. |

No need to reorganize before the first working Generate.
