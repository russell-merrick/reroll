/**
 * Monophonic MIDI helpers — scale degrees in the selected key.
 * Patterns are 16th-note grids (1 bar default), expanded to LOOP_BARS (4) for export/play.
 */

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
function degreeToMidi(keyStr, degree, octave = 3) {
  const { root, quality } = parseKey(keyStr);
  const ints = scaleDegrees(quality);
  const d = ((degree % 7) + 7) % 7;
  const interval = ints[d];
  // MIDI: C4 = 60 → octave 4
  return (octave + 1) * 12 + root + interval;
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

/** Resize note at `start` to `length` 16ths (keeps pitch/vel). */
function setNoteLength(grid, start, length) {
  const cell = grid[start];
  if (!cell) return;
  place(grid, start, cell.degree, length, cell.vel ?? 100);
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
  return role === "bass" ? 2 : 4; // bass ~C2, lead ~C4
}

function defaultPatternId(role) {
  return role === "bass" ? "root-quarters" : "scale-walk";
}

/**
 * Expand 1-bar grid to N bars of note events (default 4-bar loop).
 * @returns {{ step: number, duration: number, midi: number, vel: number, degree: number }[]}
 */
function gridToNotes(grid, keyStr, octave, bars = 4) {
  const notes = [];
  const barSteps = grid.length;
  for (let bar = 0; bar < bars; bar++) {
    for (let s = 0; s < barSteps; s++) {
      const cell = grid[s];
      if (!cell) continue;
      const step = bar * barSteps + s;
      notes.push({
        step,
        duration: cell.length || 1,
        midi: degreeToMidi(keyStr, cell.degree, octave),
        vel: cell.vel ?? 100,
        degree: cell.degree,
      });
    }
  }
  return notes;
}

/** Human summary for slot meta line */
function midiSummary(midiState, keyStr) {
  if (!midiState || !midiState.grid) return "no MIDI";
  const hits = midiState.grid.filter(Boolean).length;
  const pat =
    listPatterns().find((p) => p.id === midiState.patternId)?.name ||
    midiState.patternId ||
    "custom";
  return `${pat} · ${hits}/16 · ${keyStr} · oct ${midiState.octave}`;
}

function createMidiState(role, keyStr) {
  const patternId = defaultPatternId(role);
  const octave = defaultOctave(role);
  return {
    patternId,
    octave,
    key: keyStr,
    grid: buildPatternGrid(patternId),
    locked: false, // MIDI lock separate later if needed
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
  midiToName,
  listPatterns,
  buildPatternGrid,
  defaultOctave,
  defaultPatternId,
  gridToNotes,
  midiSummary,
  createMidiState,
  randomizeGridInKey,
  emptyGrid,
  place,
  findNoteAt,
  setNoteLength,
  clampLength,
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
