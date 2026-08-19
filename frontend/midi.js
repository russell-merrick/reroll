/**
 * MIDI helpers — scale degrees in the selected key.
 * Patterns are 16th-note grids (1 bar default). A bars*16 grid is not tiled again.
 */

const STEPS_PER_BAR = 16;
const PAD_ROLES = ["pad", "pads", "strings", "chorus", "keys"];

const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

const SCALE_INTERVALS = {
  major: [0, 2, 4, 5, 7, 9, 11],
  minor: [0, 2, 3, 5, 7, 8, 10], // natural minor
};

/**
 * Parse "F minor" / "A major" → { root: 5, quality: "minor" }
 */
function parseKey(keyStr) {
  const raw = String(keyStr || "C minor").trim();
  const m = raw.match(/^([A-G](?:#|b)?)\s*(major|minor|maj|min)?/i);
  if (!m) return { root: 0, quality: "minor", label: "C minor" };
  let name = m[1].toUpperCase();
  if (name.length > 1 && name[1] === "B") name = name[0] + "b";
  // flats → sharps for index
  const flatMap = { Db: "C#", Eb: "D#", Gb: "F#", Ab: "G#", Bb: "A#" };
  if (flatMap[name]) name = flatMap[name];
  if (name === "CB") name = "B";
  const root = NOTE_NAMES.indexOf(name);
  let q = (m[2] || "minor").toLowerCase();
  if (q === "maj") q = "major";
  if (q === "min") q = "minor";
  if (q !== "major" && q !== "minor") q = "minor";
  return {
    root: root >= 0 ? root : 0,
    quality: q,
    label: `${NOTE_NAMES[root >= 0 ? root : 0]} ${q}`,
  };
}

function scaleDegrees(quality) {
  return SCALE_INTERVALS[quality] || SCALE_INTERVALS.minor;
}

/** MIDI note from scale degree (0=root … 6=7th) + octave (MIDI octave, C4=60). */
function degreeToMidi(keyStr, degree, octave = 3, alter = 0) {
  const { root, quality } = parseKey(keyStr);
  const ints = scaleDegrees(quality);
  const d = ((degree % 7) + 7) % 7;
  const interval = ints[d];
  // MIDI: C4 = 60 → octave 4
  return (octave + 1) * 12 + root + interval + (Number(alter) || 0);
}

/** Map a pitch class to (Aeolian degree 0–6, semitone alter). Quality is ignored. */
function pcToDegreeAlter(pc, keyStr) {
  const { root } = parseKey(keyStr);
  const ints = SCALE_INTERVALS.minor;
  const rel = (((Number(pc) - root) % 12) + 12) % 12;
  for (let deg = 0; deg < ints.length; deg++) {
    if (ints[deg] === rel) return { degree: deg, alter: 0 };
  }
  for (let deg = 0; deg < ints.length; deg++) {
    if ((ints[deg] + 1) % 12 === rel) return { degree: deg, alter: 1 };
  }
  for (let deg = 0; deg < ints.length; deg++) {
    if ((ints[deg] + 11) % 12 === rel) return { degree: deg, alter: -1 };
  }
  let bestDeg = 0;
  let bestAlt = 0;
  let bestDist = 99;
  for (let deg = 0; deg < ints.length; deg++) {
    let signed = rel - ints[deg];
    if (signed > 6) signed -= 12;
    if (signed < -6) signed += 12;
    const dist = Math.abs(signed);
    if (dist < bestDist) {
      bestDist = dist;
      bestDeg = deg;
      bestAlt = signed;
    }
  }
  return { degree: bestDeg, alter: bestAlt };
}

function midiToName(midi) {
  const n = ((midi % 12) + 12) % 12;
  const oct = Math.floor(midi / 12) - 1;
  return `${NOTE_NAMES[n]}${oct}`;
}

/**
 * Pattern template: monophonic 16-step bar.
 * each step: null | { degree, length (16ths), vel }
 */
const PATTERN_LIBRARY = {
  "root-quarters": {
    id: "root-quarters",
    name: "Root quarters",
    steps: 16,
    build: () => fillHits([0, 4, 8, 12], 0, 4, 100),
  },
  "root-eighths": {
    id: "root-eighths",
    name: "Root 8ths",
    steps: 16,
    build: () => fillHits([0, 2, 4, 6, 8, 10, 12, 14], 0, 2, 90),
  },
  "offbeat-eighths": {
    id: "offbeat-eighths",
    name: "Offbeat 8ths",
    steps: 16,
    build: () => fillHits([2, 6, 10, 14], 0, 2, 95),
  },
  "root-fifth": {
    id: "root-fifth",
    name: "Root–fifth",
    steps: 16,
    build: () => {
      const g = emptyGrid(16);
      place(g, 0, 0, 2, 100);
      place(g, 4, 4, 2, 100); // 5th = degree 4
      place(g, 8, 0, 2, 100);
      place(g, 12, 4, 2, 100);
      return g;
    },
  },
  "scale-walk": {
    id: "scale-walk",
    name: "Scale walk",
    steps: 16,
    build: () => {
      const g = emptyGrid(16);
      const degs = [0, 1, 2, 3, 4, 3, 2, 1];
      degs.forEach((d, i) => place(g, i * 2, d, 2, 90));
      return g;
    },
  },
  "sparse-root": {
    id: "sparse-root",
    name: "Sparse root",
    steps: 16,
    build: () => fillHits([0, 10], 0, 4, 100),
  },
  "techno-gallop": {
    id: "techno-gallop",
    name: "Techno gallop",
    steps: 16,
    build: () => fillHits([0, 3, 6, 8, 11, 14], 0, 1, 100),
  },
  "thirds-pulse": {
    id: "thirds-pulse",
    name: "Root–third",
    steps: 16,
    build: () => {
      const g = emptyGrid(16);
      place(g, 0, 0, 2, 100);
      place(g, 4, 2, 2, 95);
      place(g, 8, 0, 2, 100);
      place(g, 12, 2, 2, 95);
      return g;
    },
  },
};

function emptyGrid(n) {
  return Array.from({ length: n }, () => null);
}

/** Clamp note length so it fits the bar from `step`. */
function clampLength(step, length, barSteps = 16) {
  const len = Math.max(1, Math.floor(Number(length) || 1));
  return Math.max(1, Math.min(len, barSteps - step));
}

/**
 * Note covering `step`, if any (start index + cell).
 * Grid stores note starts only; body cells are null.
 */
function findNoteAt(grid, step) {
  if (!grid || step < 0 || step >= grid.length) return null;
  for (let s = 0; s <= step; s++) {
    const cell = grid[s];
    if (!cell) continue;
    const len = clampLength(s, cell.length || 1, grid.length);
    if (s + len > step) return { start: s, cell, length: len };
  }
  return null;
}

/**
 * Place a monophonic note. Removes any overlapping notes.
 * Body cells stay null; only the start holds { degree, length, vel }.
 */
function place(grid, step, degree, length, vel) {
  if (step < 0 || step >= grid.length) return;
  const len = clampLength(step, length, grid.length);
  const newEnd = step + len;
  for (let s = 0; s < grid.length; s++) {
    const cell = grid[s];
    if (!cell) continue;
    const end = s + clampLength(s, cell.length || 1, grid.length);
    if (s < newEnd && end > step) grid[s] = null;
  }
  grid[step] = {
    degree: ((Number(degree) % 7) + 7) % 7,
    length: len,
    vel: vel ?? 100,
  };
}

/**
 * Place a polyphonic cell. Clears overlaps; keeps `voices`.
 * Primary degree/vel stay on the cell for the mono editor + summary.
 */
function placeVoices(grid, step, voices, length, vel) {
  if (!grid || step < 0 || step >= grid.length) return;
  const vs = Array.isArray(voices)
    ? voices.filter((v) => v && typeof v === "object").map((v) => ({ ...v }))
    : [];
  if (!vs.length) return;
  const len = clampLength(step, length, grid.length);
  const newEnd = step + len;
  for (let s = 0; s < grid.length; s++) {
    const cell = grid[s];
    if (!cell) continue;
    const end = s + clampLength(s, cell.length || 1, grid.length);
    if (s < newEnd && end > step) grid[s] = null;
  }
  const primary = vs[0];
  const cell = {
    degree: ((Number(primary.degree) % 7) + 7) % 7,
    length: len,
    vel: vel ?? primary.vel ?? 100,
    voices: vs,
  };
  if (primary.alter) cell.alter = primary.alter;
  grid[step] = cell;
}

/** Resize note at `start` to `length` 16ths (keeps pitch/vel/voices). */
function setNoteLength(grid, start, length) {
  const cell = grid[start];
  if (!cell) return;
  if (Array.isArray(cell.voices) && cell.voices.length) {
    const voices = cell.voices.map((v) => ({ ...v }));
    const deg = cell.degree;
    const alter = cell.alter;
    const oct = cell.oct;
    placeVoices(grid, start, voices, length, cell.vel ?? 100);
    if (grid[start]) {
      grid[start].degree = deg;
      if (alter) grid[start].alter = alter;
      if (oct != null) grid[start].oct = oct;
    }
    return;
  }
  const alter = cell.alter;
  const oct = cell.oct;
  place(grid, start, cell.degree, length, cell.vel ?? 100);
  if (grid[start]) {
    if (alter) grid[start].alter = alter;
    if (oct != null) grid[start].oct = oct;
  }
}

/** Cycle inversion: move the lowest sounding voice up one octave. */
function invertCellVoices(cell, octave, keyStr) {
  if (!cell || typeof cell !== "object") return cell;
  const key = keyStr || "C minor";
  const oct0 = octave ?? 3;
  let voices;
  if (Array.isArray(cell.voices) && cell.voices.length) {
    voices = cell.voices.map((v) => ({ ...v }));
  } else {
    voices = [
      {
        degree: cell.degree ?? 0,
        oct: cell.oct ?? oct0,
        vel: cell.vel ?? 100,
      },
    ];
    if (cell.alter) voices[0].alter = cell.alter;
  }
  let lo = 0;
  let loMidi = Infinity;
  for (let i = 0; i < voices.length; i++) {
    const oct = voices[i].oct ?? oct0;
    const midi = degreeToMidi(key, voices[i].degree ?? 0, oct, voices[i].alter ?? 0);
    if (midi < loMidi) {
      loMidi = midi;
      lo = i;
    }
  }
  const moved = { ...voices[lo], oct: (voices[lo].oct ?? oct0) + 1 };
  voices.splice(lo, 1);
  voices.push(moved);
  cell.voices = voices;
  cell.degree = voices[0].degree ?? cell.degree;
  return cell;
}

function fillHits(steps, degree, length, vel) {
  const g = emptyGrid(16);
  for (const s of steps) place(g, s, degree, length, vel);
  return g;
}

function listPatterns() {
  return Object.values(PATTERN_LIBRARY).map((p) => ({ id: p.id, name: p.name }));
}

function buildPatternGrid(patternId) {
  const p = PATTERN_LIBRARY[patternId] || PATTERN_LIBRARY["root-quarters"];
  return p.build().map((cell) => (cell ? { ...cell } : null));
}

function defaultOctave(role) {
  if (role === "bass") return 2;
  if (PAD_ROLES.includes(role)) return 3;
  return 4;
}

function defaultPatternId(role) {
  return role === "bass" ? "root-quarters" : "techno-gallop";
}

/** Repeat count: a bars*16 grid is already a full loop — do not tile again. */
function expandBars(grid, bars) {
  const n = (grid && grid.length) || STEPS_PER_BAR;
  if (n === Number(bars) * STEPS_PER_BAR) return 1;
  return Math.max(1, Number(bars) || 1);
}

/** Voices to emit. Missing/empty `voices` → the cell's single degree. */
function cellVoices(cell) {
  if (!cell || typeof cell !== "object") return [];
  if (Array.isArray(cell.voices) && cell.voices.length) return cell.voices;
  const out = {
    degree: cell.degree ?? 0,
    alter: cell.alter ?? 0,
    vel: cell.vel ?? 100,
  };
  if (cell.oct != null) out.oct = cell.oct;
  return [out];
}

/**
 * Expand 1-bar grid to N bars of note events (default 4-bar loop).
 * If grid.length === bars*16, emit once (no double-tile).
 * @returns {{ step: number, duration: number, midi: number, vel: number, degree: number }[]}
 */
function gridToNotes(grid, keyStr, octave, bars = 4) {
  const notes = [];
  if (!grid || !grid.length) return notes;
  const barSteps = grid.length;
  const reps = expandBars(grid, bars);
  for (let bar = 0; bar < reps; bar++) {
    for (let s = 0; s < barSteps; s++) {
      const cell = grid[s];
      if (!cell) continue;
      const step = bar * barSteps + s;
      for (const voice of cellVoices(cell)) {
        const deg = voice.degree ?? cell.degree ?? 0;
        const octv = voice.oct ?? cell.oct ?? octave;
        const alter = voice.alter ?? cell.alter ?? 0;
        const vel = voice.vel ?? cell.vel ?? 100;
        notes.push({
          step,
          duration: cell.length || 1,
          midi: degreeToMidi(keyStr, deg, octv, alter),
          vel,
          degree: deg,
        });
      }
    }
  }
  return notes;
}

/** Human summary for slot meta line */
function midiSummary(midiState, keyStr) {
  if (!midiState || !midiState.grid) return "no MIDI";
  const hits = midiState.grid.filter(Boolean).length;
  const n = midiState.grid.length || STEPS_PER_BAR;
  const pat =
    listPatterns().find((p) => p.id === midiState.patternId)?.name ||
    midiState.patternId ||
    "custom";
  const key = keyStr || midiState.key || "";
  return `${pat} · ${hits}/${n} · ${key} · oct ${midiState.octave}`;
}

function createMidiState(role, keyStr) {
  const patternId = defaultPatternId(role);
  const octave = defaultOctave(role);
  return {
    patternId,
    octave,
    key: keyStr,
    bars: 1,
    source: "pattern",
    grid: buildPatternGrid(patternId),
    locked: false,
    density: 0.5,
    variance: 0.5,
    length: 0.5,
  };
}

function randomizeGridInKey(role) {
  // pick a library pattern at random
  const ids = Object.keys(PATTERN_LIBRARY);
  const id = ids[Math.floor(Math.random() * ids.length)];
  return { patternId: id, grid: buildPatternGrid(id) };
}

// browser global
window.MidiEngine = {
  parseKey,
  degreeToMidi,
  pcToDegreeAlter,
  midiToName,
  listPatterns,
  buildPatternGrid,
  defaultOctave,
  defaultPatternId,
  expandBars,
  cellVoices,
  gridToNotes,
  midiSummary,
  createMidiState,
  randomizeGridInKey,
  emptyGrid,
  place,
  placeVoices,
  invertCellVoices,
  findNoteAt,
  setNoteLength,
  clampLength,
  STEPS_PER_BAR,
  PAD_ROLES,
  PATTERN_LIBRARY,
  NOTE_NAMES,
  /** Common lengths in 16ths for the editor toolbar */
  NOTE_LENGTHS: [
    { value: 1, label: "1/16" },
    { value: 2, label: "1/8" },
    { value: 4, label: "1/4" },
    { value: 8, label: "1/2" },
    { value: 16, label: "1 bar" },
  ],
};
