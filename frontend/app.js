/**
 * Austin Russell Loop Machine — FastAPI client + Web Audio preview.
 * Open via http://127.0.0.1:8000 (not file://).
 */

const state = {
  /** @type {string[]} ordered track ids */
  trackOrder: [],
  /** @type {Record<string, object>} id -> track state */
  slots: {},
  options: {
    filterRisers: true,
    /** Skip stock Serum banks; only Splice/User */
    filterFactorySerum: false,
    /** Include Serum 1 (.fxp) in Generate / dice */
    serum1: true,
    /** Include Serum 2 (.SerumPreset) in Generate / dice */
    serum2: true,
    /** instrument id → enabled for default track stack */
    instruments: {},
  },
  /** Last saved loop id (for optional overwrite context) */
  currentLoopId: null,
  /** Last saved / loaded display name */
  currentLoopName: null,
};

/**
 * Options → Default instruments (order = track stack order).
 * defaultOn = checked when no saved preference.
 */
const INSTRUMENT_DEFS = [
  { id: "kick", label: "Kick", type: "kick", defaultOn: true, tip: "Kick samples" },
  { id: "hats", label: "Hats", type: "hats", defaultOn: true, tip: "Hi-hat samples" },
  { id: "clap", label: "Clap", type: "clap", defaultOn: true, tip: "Clap / snare samples" },
  {
    id: "lead_audio",
    label: "Lead (audio)",
    type: "lead_audio",
    defaultOn: true,
    tip: "Lead / synth audio samples (not Serum)",
  },
  {
    id: "bass",
    label: "Bass (Serum)",
    type: "bass",
    defaultOn: true,
    tip: "Serum bass presets + MIDI",
  },
  { id: "brass", label: "Brass", type: "brass", defaultOn: false, tip: "Serum brass" },
  { id: "chorus", label: "Chorus", type: "chorus", defaultOn: false, tip: "Serum chords / chorus-like" },
  { id: "pads", label: "Pads", type: "pad", defaultOn: false, tip: "Serum pads" },
  { id: "vocals", label: "Vocals", type: "vocal", defaultOn: false, tip: "Vocal samples" },
  { id: "guitar", label: "Guitar", type: "guitar", defaultOn: false, tip: "Serum guitar" },
  { id: "keys", label: "Keys", type: "keys", defaultOn: false, tip: "Serum keys / piano" },
  { id: "strings", label: "Strings", type: "strings", defaultOn: false, tip: "Serum strings / pads" },
];

function defaultInstrumentsMap() {
  const out = {};
  for (const d of INSTRUMENT_DEFS) out[d.id] = Boolean(d.defaultOn);
  return out;
}

function ensureInstrumentsState() {
  if (!state.options.instruments || typeof state.options.instruments !== "object") {
    state.options.instruments = defaultInstrumentsMap();
    return;
  }
  const merged = defaultInstrumentsMap();
  for (const d of INSTRUMENT_DEFS) {
    if (Object.prototype.hasOwnProperty.call(state.options.instruments, d.id)) {
      merged[d.id] = Boolean(state.options.instruments[d.id]);
    }
  }
  state.options.instruments = merged;
}

function isInstrumentEnabled(id) {
  ensureInstrumentsState();
  return Boolean(state.options.instruments[id]);
}

/** Ordered track types from Options checkboxes */
function enabledDefaultTrackTypes() {
  ensureInstrumentsState();
  return INSTRUMENT_DEFS.filter((d) => state.options.instruments[d.id]).map((d) => d.type);
}

/** Default stack on first load — derived from instrument checkboxes */
function getDefaultTrackTypes() {
  const types = enabledDefaultTrackTypes();
  return types.length ? types : ["kick"];
}

const SAMPLE_TYPES = new Set([
  "kick",
  "clap",
  "hats",
  "perc",
  "fx",
  "snare",
  "vocal",
  "loop",
  "lead_audio",
]);

/** @deprecated use activeTrackIds() */
const ALL_ROLES = ["kick", "clap", "hats", "bass", "lead_audio"];

let trackSeq = 0;

function activeTrackIds() {
  return state.trackOrder.filter((id) => state.slots[id]);
}

function baseType(id) {
  const s = state.slots[id];
  if (s?.type) return s.type;
  return String(id).split("__")[0];
}

function isSerumType(type) {
  return !SAMPLE_TYPES.has(type);
}

function isSerumTrack(id) {
  const s = state.slots[id];
  if (!s) return false;
  if (s.kind === "serum") return true;
  return isSerumType(baseType(id));
}

function newTrackId(type) {
  trackSeq += 1;
  // Keep first of each type as bare name for readability
  if (!state.slots[type] && !state.trackOrder.includes(type)) return type;
  return `${type}__${trackSeq}`;
}

/**
 * Open MIDI editors keyed by track id.
 * @type {Record<string, { role: string, draft: object, root: HTMLElement }>}
 */
let midiEditors = {};

/** @type {AudioContext | null} */
let audioCtx = null;
/** @type {Map<string, AudioBuffer>} */
const bufferCache = new Map();
/** @type {Array<{src: AudioBufferSourceNode, gain: GainNode}>} */
let activeSources = [];
let loopTimer = null;
/** @type {ReturnType<typeof setInterval> | null} */
let activePulseTimer = null;
let isPlaying = false;
/** True while samples/Serum are loading before the first note. */
let isPlayPending = false;
/** Nested count of async work (Serum bounce, sample load, generate…). */
let transportBusyCount = 0;
/** Optional label while busy (e.g. "Rendering bass"). */
let transportBusyLabel = "";

/** Role whose per-track ▶ is looping, or null. */
let previewLoopRole = null;
/** @type {ReturnType<typeof setTimeout> | null} */
let previewMidiTimer = null;
/** Bumps when preview is cancelled mid-load. */
let previewGen = 0;

/** Per-role master gains — mute flips these live while the loop plays. */
/** @type {Record<string, GainNode>} */
let trackGains = {};

/** Session loop length in bars — change this (and restart play) to try 8 later. */
const LOOP_BARS = 4;

/** Look-ahead loop scheduler — reads BPM live so tempo can change mid-play. */
const scheduler = {
  /** @type {Record<string, AudioBuffer>} */
  buffers: {},
  /** @type {string[]} */
  playable: [],
  /** Roles with long/loop WAVs — started once, not re-triggered on every step */
  /** @type {Record<string, boolean>} */
  phraseRoles: {},
  nextStep: 0,
  nextNoteTime: 0,
  /** LOOP_BARS × 16 sixteenths (4 bars → 16 quarter-note kicks). */
  totalSteps: LOOP_BARS * 16,
  /** @type {ReturnType<typeof setInterval> | null} */
  timerId: null,
  bars: LOOP_BARS,
};

const LOOKAHEAD_SEC = 0.15;
const SCHEDULE_MS = 25;
/** Lead time before first scheduled note after Play (must clear setup work). */
const START_LEAD_SEC = 0.12;

// Simple 16th-note patterns over 1 bar (repeated for LOOP_BARS)
const PATTERNS = {
  kick: [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0],
  clap: [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
  hats: [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 1],
  perc: [0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1, 0],
  fx: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], // one-shot at start if present
  // One-shots / stabs — long loops use phrase beds instead
  lead_audio: [1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0],
  vocal: [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
};

const SLOT_GAIN = {
  kick: 1.0,
  clap: 0.85,
  hats: 0.45,
  perc: 0.55,
  fx: 0.5,
  vocal: 0.55,
  lead_audio: 0.55,
  bass: 0.7,
  lead: 0.6,
  brass: 0.55,
  chorus: 0.5,
  pad: 0.5,
  guitar: 0.55,
  keys: 0.55,
  strings: 0.5,
};

function getBpm() {
  const n = Number($("#bpm")?.value || 140);
  if (!Number.isFinite(n)) return 140;
  return Math.min(200, Math.max(60, n));
}

function secPer16th() {
  return 60 / getBpm() / 4;
}

// ── Loop waveform overview (full-width, above Loop) ─────────────────────────
/** @type {{ peaks: Float32Array | null, bins: number, dirty: boolean, raf: number, lastProgress: number }} */
const waveView = {
  peaks: null,
  bins: 0,
  dirty: true,
  raf: 0,
  lastProgress: 0,
};

function markWaveDirty() {
  waveView.dirty = true;
}

/**
 * Fractional progress through the current loop cycle [0, 1).
 * Derived from the look-ahead scheduler clock so it stays kick-locked.
 */
function getCycleProgress() {
  if (!isPlaying || !audioCtx) return 0;
  const sp = secPer16th();
  if (!(sp > 0)) return 0;
  const cycle = serumCycleSteps();
  if (cycle <= 0) return 0;
  let stepF = scheduler.nextStep - (scheduler.nextNoteTime - audioCtx.currentTime) / sp;
  stepF = ((stepF % cycle) + cycle) % cycle;
  return stepF / cycle;
}

/**
 * Stamp max-abs peaks from a buffer into [startFrac, endFrac) of the peaks array.
 * Maps the full buffer length across that fraction range (used for stems & hits).
 */
function stampBufferPeaks(peaks, buffer, gain, startFrac, endFrac) {
  if (!buffer || !peaks?.length) return;
  const ch = buffer.numberOfChannels > 0 ? buffer.getChannelData(0) : null;
  if (!ch || !ch.length) return;
  const n = ch.length;
  const bins = peaks.length;
  const i0 = Math.max(0, Math.floor(startFrac * bins));
  const i1 = Math.min(bins, Math.ceil(endFrac * bins));
  if (i1 <= i0) return;
  const span = i1 - i0;
  const g = Math.max(0, Number(gain) || 0);
  if (g <= 0) return;

  for (let i = i0; i < i1; i++) {
    const t0 = (i - i0) / span;
    const t1 = (i + 1 - i0) / span;
    let s0 = Math.floor(t0 * n);
    let s1 = Math.ceil(t1 * n);
    if (s1 <= s0) s1 = s0 + 1;
    if (s0 >= n) continue;
    if (s1 > n) s1 = n;
    // Subsample long ranges so rebuild stays cheap
    const range = s1 - s0;
    const step = range > 256 ? Math.floor(range / 128) : 1;
    let m = 0;
    for (let s = s0; s < s1; s += step) {
      const v = Math.abs(ch[s]);
      if (v > m) m = v;
    }
    const val = m * g;
    if (val > peaks[i]) peaks[i] = val;
  }
}

/** Paint one-shot starting at cycle fraction `startFrac` for its natural duration. */
function stampHitPeaks(peaks, buffer, gain, startFrac, cycleSec) {
  if (!buffer || cycleSec <= 0) return;
  // Cap visual length so a long one-shot doesn't fill the whole bar like a pad,
  // but keep enough width to see the hit (~1/8 note min, ~1/2 note max of cycle).
  const rawFrac = buffer.duration / cycleSec;
  const durFrac = Math.min(1 - startFrac, Math.max(1 / 32, Math.min(rawFrac, 0.08)));
  if (durFrac <= 0.0005) return;
  stampBufferPeaks(peaks, buffer, gain, startFrac, startFrac + durFrac);
}

/** Normalize a peak lane in-place to 0..1 (peak = 1). Returns peak before norm. */
function normalizePeakLane(lane) {
  let max = 0;
  for (let i = 0; i < lane.length; i++) if (lane[i] > max) max = lane[i];
  if (max > 1e-6) {
    const inv = 1 / max;
    for (let i = 0; i < lane.length; i++) lane[i] *= inv;
  }
  return max;
}

/**
 * Visual weight after each track is peak-normalized to 1.
 * Overview is for shape readability, not true mix balance — kicks would
 * otherwise set the global scale and hide quieter Serum/hats body.
 */
function waveVisualWeight(type, { stem = false } = {}) {
  if (stem) return 1.05; // full-cycle stems: slightly favor sustain body
  switch (type) {
    case "kick":
      return 0.55; // hot spikes — keep present but not dominant
    case "clap":
    case "snare":
      return 0.65;
    case "hats":
      return 0.75;
    case "perc":
      return 0.7;
    default:
      return 1.0;
  }
}

/**
 * Approximate loop mix peaks from scheduler buffers + MIDI grid blips.
 *
 * Scaling model (important):
 *  1) Paint each track into its own lane at raw amplitude
 *  2) Peak-normalize that lane → 0..1  (kick loudness no longer sets the mix)
 *  3) Blend with light type weights + soft curve for body under spikes
 */
function buildLoopPeaks(binCount) {
  const peaks = new Float32Array(binCount);
  const cycle = serumCycleSteps();
  const cycleSec = cycle * secPer16th();
  if (cycleSec <= 0 || binCount <= 0) return peaks;

  // Sum of normalized lanes (not pure max) so overlapping kick+serum both contribute
  const sum = new Float32Array(binCount);
  const mx = new Float32Array(binCount);
  let laneCount = 0;

  function blendLane(lane, weight) {
    if (normalizePeakLane(lane) < 1e-6) return;
    const w = Math.max(0.05, weight);
    for (let i = 0; i < binCount; i++) {
      const v = lane[i] * w;
      sum[i] += v;
      if (v > mx[i]) mx[i] = v;
    }
    laneCount += 1;
  }

  // Audio buffers (samples + Serum stems) — one lane each
  for (const role of Object.keys(scheduler.buffers || {})) {
    const buffer = scheduler.buffers[role];
    if (!buffer) continue;
    const t = baseType(role);
    const lane = new Float32Array(binCount);
    const muteScale = isTrackAudible(role) ? 1 : 0.12;
    const isStem = Boolean(serumStemRoles[role] || scheduler.phraseRoles[role]);

    if (isStem) {
      stampBufferPeaks(lane, buffer, 1, 0, 1);
    } else {
      const pat = PATTERNS[t];
      if (pat) {
        for (let step = 0; step < cycle; step++) {
          if (!pat[step % 16]) continue;
          stampHitPeaks(lane, buffer, 1, step / cycle, cycleSec);
        }
      } else {
        stampHitPeaks(lane, buffer, 1, 0, cycleSec);
      }
    }

    blendLane(lane, waveVisualWeight(t, { stem: isStem }) * muteScale);
  }

  // MIDI-only voices (JS synth fallback or pre-bounce)
  for (const role of activeTrackIds()) {
    if (!isSerumTrack(role)) continue;
    if (scheduler.buffers[role] && serumStemRoles[role]) continue;
    const midi = state.slots[role]?.midi;
    if (!midi?.grid || !window.MidiEngine) continue;
    const lane = new Float32Array(binCount);
    const muteScale = isTrackAudible(role) ? 1 : 0.12;
    const notes = MidiEngine.gridToNotes(
      midi.grid,
      midi.key || $("#key")?.value || "F minor",
      midi.octave ?? 3,
      scheduler.bars || LOOP_BARS
    );
    for (const n of notes) {
      const start = n.step / cycle;
      const len = Math.max(1, n.duration || 1) / cycle;
      const i0 = Math.max(0, Math.floor(start * binCount));
      const i1 = Math.min(binCount, Math.ceil((start + len) * binCount));
      for (let i = i0; i < i1; i++) {
        const local = (i - i0) / Math.max(1, i1 - i0);
        const env = Math.exp(-local * 3.2) * (0.4 + 0.6 * ((n.vel || 100) / 127));
        if (env > lane[i]) lane[i] = env;
      }
    }
    blendLane(lane, 1.0 * muteScale);
  }

  if (!laneCount) return peaks;

  // 70% max envelope (transients) + 30% sum (layered body) — keeps kicks sharp
  // while Serum between hits stays above the noise floor of the display
  for (let i = 0; i < binCount; i++) {
    const avg = sum[i] / laneCount;
    peaks[i] = mx[i] * 0.7 + avg * 0.3;
  }

  // Compress dynamic range for display (sqrt-ish) so quieter body lifts
  for (let i = 0; i < binCount; i++) {
    if (peaks[i] > 0) peaks[i] = Math.pow(peaks[i], 0.55);
  }
  normalizePeakLane(peaks);
  return peaks;
}

function waveCanvasSize() {
  const canvas = $("#wave-canvas");
  const wrap = canvas?.parentElement;
  if (!canvas || !wrap) return { canvas: null, w: 0, h: 0, dpr: 1 };
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const cssW = Math.max(1, wrap.clientWidth || 1);
  const cssH = Math.max(1, wrap.clientHeight || 88);
  const w = Math.round(cssW * dpr);
  const h = Math.round(cssH * dpr);
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
    waveView.dirty = true;
  }
  return { canvas, w, h, dpr };
}

function drawWaveformFrame() {
  const { canvas, w, h } = waveCanvasSize();
  if (!canvas || w < 2 || h < 2) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const bins = w;
  if (waveView.dirty || !waveView.peaks || waveView.bins !== bins) {
    // Only rebuild peaks when we have something to show (playing or buffers present)
    const hasAudio =
      Object.keys(scheduler.buffers || {}).length > 0 ||
      activeTrackIds().some((r) => state.slots[r]?.midi?.grid);
    waveView.peaks = hasAudio ? buildLoopPeaks(bins) : new Float32Array(bins);
    waveView.bins = bins;
    waveView.dirty = false;
  }

  const peaks = waveView.peaks;
  const mid = h * 0.5;
  const amp = h * 0.42;

  ctx.clearRect(0, 0, w, h);

  // Beat / bar grid
  const cycle = serumCycleSteps();
  const bars = scheduler.bars || LOOP_BARS;
  ctx.lineWidth = 1;
  for (let b = 0; b <= bars; b++) {
    const x = Math.round((b / bars) * w) + 0.5;
    ctx.strokeStyle = b === 0 || b === bars ? "rgba(255,255,255,0.08)" : "rgba(255,255,255,0.045)";
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
  }
  // Quarter-note ticks
  const quarters = bars * 4;
  for (let q = 1; q < quarters; q++) {
    if (q % 4 === 0) continue;
    const x = Math.round((q / quarters) * w) + 0.5;
    ctx.strokeStyle = "rgba(255,255,255,0.03)";
    ctx.beginPath();
    ctx.moveTo(x, h * 0.15);
    ctx.lineTo(x, h * 0.85);
    ctx.stroke();
  }

  // Center line
  ctx.strokeStyle = "rgba(255,255,255,0.06)";
  ctx.beginPath();
  ctx.moveTo(0, mid + 0.5);
  ctx.lineTo(w, mid + 0.5);
  ctx.stroke();

  // Waveform fill (mirrored)
  const hasSignal = peaks && peaks.length;
  let any = false;
  if (hasSignal) {
    for (let i = 0; i < peaks.length; i++) {
      if (peaks[i] > 0.01) {
        any = true;
        break;
      }
    }
  }

  if (any) {
    ctx.beginPath();
    ctx.moveTo(0, mid);
    for (let i = 0; i < bins; i++) {
      const y = mid - peaks[i] * amp;
      ctx.lineTo(i + 0.5, y);
    }
    for (let i = bins - 1; i >= 0; i--) {
      const y = mid + peaks[i] * amp;
      ctx.lineTo(i + 0.5, y);
    }
    ctx.closePath();
    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, "rgba(110, 231, 183, 0.55)");
    grad.addColorStop(0.5, "rgba(110, 231, 183, 0.22)");
    grad.addColorStop(1, "rgba(110, 231, 183, 0.55)");
    ctx.fillStyle = grad;
    ctx.fill();

    // Top outline
    ctx.beginPath();
    for (let i = 0; i < bins; i++) {
      const y = mid - peaks[i] * amp;
      if (i === 0) ctx.moveTo(i + 0.5, y);
      else ctx.lineTo(i + 0.5, y);
    }
    ctx.strokeStyle = "rgba(110, 231, 183, 0.75)";
    ctx.lineWidth = Math.max(1, window.devicePixelRatio || 1);
    ctx.stroke();
  } else {
    ctx.fillStyle = "rgba(139, 147, 167, 0.35)";
    ctx.font = `${Math.round(11 * (window.devicePixelRatio || 1))}px ${getComputedStyle(document.body).fontFamily || "sans-serif"}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("Play to build waveform", w / 2, mid);
  }

  // Played region dim overlay + playhead
  const progress = isPlaying ? getCycleProgress() : waveView.lastProgress;
  if (isPlaying) waveView.lastProgress = progress;
  const px = progress * w;

  if (isPlaying || progress > 0.001) {
    ctx.fillStyle = "rgba(12, 13, 16, 0.35)";
    ctx.fillRect(0, 0, px, h);
  }

  if (isPlaying || any) {
    // Playhead
    ctx.strokeStyle = isPlaying ? "rgba(251, 191, 36, 0.95)" : "rgba(251, 191, 36, 0.4)";
    ctx.lineWidth = Math.max(1.5, (window.devicePixelRatio || 1) * 1.5);
    ctx.beginPath();
    ctx.moveTo(px + 0.5, 0);
    ctx.lineTo(px + 0.5, h);
    ctx.stroke();
    // Tip diamond
    const tip = 4 * (window.devicePixelRatio || 1);
    ctx.fillStyle = isPlaying ? "#fbbf24" : "rgba(251, 191, 36, 0.5)";
    ctx.beginPath();
    ctx.moveTo(px, tip);
    ctx.lineTo(px + tip, 0);
    ctx.lineTo(px - tip, 0);
    ctx.closePath();
    ctx.fill();
  }

  // Meta label
  const meta = $("#wave-meta");
  if (meta) {
    const bpm = getBpm();
    if (isPlaying) {
      const bar = Math.min(bars, Math.floor(progress * bars) + 1);
      const beat = Math.floor(((progress * bars) % 1) * 4) + 1;
      meta.textContent = `${bpm} BPM · ${bars} bars · bar ${bar}.${beat}`;
    } else if (any) {
      meta.textContent = `Stopped · ${bars} bars @ ${bpm} BPM`;
    } else {
      meta.textContent = "Idle · play to build";
    }
  }

  const section = $("#wave-overview");
  section?.classList.toggle("is-playing", isPlaying);
}

function waveRafLoop() {
  waveView.raf = 0;
  drawWaveformFrame();
  if (isPlaying) {
    waveView.raf = requestAnimationFrame(waveRafLoop);
  }
}

function startWaveRaf() {
  if (waveView.raf) return;
  waveView.raf = requestAnimationFrame(waveRafLoop);
}

function stopWaveRaf() {
  if (waveView.raf) {
    cancelAnimationFrame(waveView.raf);
    waveView.raf = 0;
  }
  drawWaveformFrame();
}

function initWaveOverview() {
  markWaveDirty();
  drawWaveformFrame();
  const wrap = $("#wave-canvas")?.parentElement;
  if (wrap && typeof ResizeObserver !== "undefined") {
    const ro = new ResizeObserver(() => {
      markWaveDirty();
      drawWaveformFrame();
    });
    ro.observe(wrap);
  } else {
    window.addEventListener("resize", () => {
      markWaveDirty();
      drawWaveformFrame();
    });
  }
}

function playingStatusLine() {
  const bpm = getBpm();
  const sampleSlots = ["kick", "clap", "hats", "perc", "fx"];
  const ids = activeTrackIds();
  const mutedList = ids.filter((r) => state.slots[r]?.muted).join(", ");
  const soloList = ids.filter((r) => state.slots[r]?.solo).join(", ");
  const midiOn = ids.filter((r) => isSerumTrack(r) && state.slots[r]?.midi?.grid);
  let note = "";
  if (soloList) note += ` · solo: ${soloList}`;
  if (mutedList) note += ` · muted: ${mutedList}`;
  if (midiOn.length) note += ` · MIDI synth: ${midiOn.join(", ")}`;
  const drums = scheduler.playable.join(", ") || "no drums";
  return `Playing loop @ ${bpm} BPM · ${drums}${note} · BPM live`;
}

/**
 * Transport strip: grey idle · green breathe playing · yellow busy (render/load).
 * Busy wins over playing so Serum bounces show work in progress.
 */
function updateStatusBar() {
  const bar = $("#status-bar");
  const labelEl = $("#status-bar-label");
  if (!bar) return;
  const busy = transportBusyCount > 0 || isPlayPending;
  const playing = isPlaying && !busy;
  const idle = !busy && !isPlaying;

  bar.classList.toggle("is-busy", busy);
  bar.classList.toggle("is-playing", playing);
  bar.classList.toggle("is-idle", idle);

  if (labelEl) {
    if (busy) {
      labelEl.textContent =
        transportBusyLabel ||
        (isPlayPending ? "Loading…" : "Working…");
    } else if (isPlaying) {
      labelEl.textContent = "Playing";
    } else {
      labelEl.textContent = "Idle";
    }
  }
}

/** Mark async work (Serum .wav bounce, generate, etc.). Nested-safe. */
function beginTransportBusy(label = "") {
  transportBusyCount += 1;
  if (label) transportBusyLabel = label;
  updateStatusBar();
}

function endTransportBusy() {
  transportBusyCount = Math.max(0, transportBusyCount - 1);
  if (transportBusyCount === 0) transportBusyLabel = "";
  updateStatusBar();
}

function updatePlayButton() {
  const btn = $("#btn-play");
  if (!btn) return;
  const on = isPlaying || isPlayPending;
  btn.classList.toggle("on", on);
  btn.setAttribute("aria-pressed", String(on));
  const label = on ? "Stop" : "Play";
  const iconClass = on ? "emoji-stop" : "emoji-play";
  btn.innerHTML = `<span class="${iconClass}" aria-hidden="true">${on ? "⏹" : "▶"}</span> ${label}`;
  btn.dataset.tip = on
    ? "Stop looping playback (Space)"
    : "Play loop (Space) · repeats until stop · BPM live";
  updateStatusBar();
}

function $(sel, root = document) {
  return root.querySelector(sel);
}

/** Truncate display names so long paths don't shove track icons off-screen. */
const DISPLAY_NAME_MAX = 50;

function truncateDisplayName(name, max = DISPLAY_NAME_MAX) {
  const s = String(name ?? "").trim();
  if (!s) return "—";
  if (s.length <= max) return s;
  if (max <= 3) return s.slice(0, max);
  return s.slice(0, max - 3) + "...";
}

/** Set slot title line; full name in title attr for hover. */
function setSlotNameEl(nameEl, fullName) {
  if (!nameEl) return;
  const full = String(fullName ?? "").trim() || "—";
  nameEl.textContent = truncateDisplayName(full);
  if (full !== "—" && full.length > DISPLAY_NAME_MAX) {
    nameEl.title = full;
    nameEl.dataset.tip = full;
  } else {
    nameEl.removeAttribute("title");
    delete nameEl.dataset.tip;
  }
}

function $all(sel, root = document) {
  return [...root.querySelectorAll(sel)];
}

function setStatus(msg) {
  const el = $("#status");
  if (el) el.textContent = msg;
}

function setTip(msg, { idle = false } = {}) {
  const el = $("#tip");
  if (!el) return;
  el.textContent = msg || "Hover a control for help";
  el.classList.toggle("is-idle", idle || !msg);
}

function tipForButton(btn) {
  if (!btn || btn.nodeType !== 1) return "";
  if (btn.dataset.tip) return btn.dataset.tip;
  if (btn.classList.contains("mute")) {
    return btn.classList.contains("on")
      ? "Unmute this track (live while playing)"
      : "Mute this track (live while playing)";
  }
  if (btn.classList.contains("solo")) {
    return btn.classList.contains("on")
      ? "Unsolo this track"
      : "Solo this track (mute others)";
  }
  if (btn.classList.contains("lock")) {
    return btn.classList.contains("on")
      ? "Unlock — allow Generate to change this track"
      : "Lock — keep this sound on Generate";
  }
  if (btn.classList.contains("dice")) return "Reroll this track only";
  if (btn.classList.contains("loop-delete")) return "Delete this saved loop";
  if (btn.classList.contains("delete")) return "Remove this track from the stack";
  if (btn.classList.contains("serum-m")) return "Edit MIDI pattern";
  if (btn.classList.contains("serum-engine")) return "Serum engine filter (use Options)";

  return btn.getAttribute("aria-label") || "";
}

/** Closest element that should drive the docked help tip. */
function tipTargetFrom(el) {
  if (!el || el.nodeType !== 1) return null;
  return el.closest(
    "button, .btn, .icon-btn, .spotify-link, a[data-tip], label[data-tip], [data-tip], select, input, .slot-name"
  );
}

/**
 * Docked help tip — event delegation so dynamically added track buttons
 * (mute/solo/lock/dice/trash) work without rebinding.
 */
function initBottomTips() {
  // Static session field tips
  [
    ["#bpm", "Tempo — changes live while the loop is playing"],
    ["#key", "Key for future MIDI (not used for sample pick yet)"],
    ["#style", "Style / genre label (not used for pick yet)"],
  ].forEach(([sel, tip]) => {
    const el = $(sel);
    if (el) el.dataset.tip = tip;
  });

  let activeTipEl = null;

  const showFor = (el) => {
    const target = tipTargetFrom(el);
    if (!target) return;
    // Prefer data-tip / role-specific text; fall back to title for truncated names
    let text = tipForButton(target);
    if (!text && target.title) text = target.title;
    if (!text) return;
    activeTipEl = target;
    setTip(text, { idle: false });
  };

  const clearIfLeft = (related) => {
    if (activeTipEl && related && activeTipEl.contains(related)) return;
    if (activeTipEl && related && tipTargetFrom(related) === activeTipEl) return;
    activeTipEl = null;
    setTip("Hover a control for help", { idle: true });
  };

  // mouseover/out bubble; mouseenter does not
  document.addEventListener("mouseover", (ev) => {
    const t = tipTargetFrom(ev.target);
    if (!t) return;
    showFor(t);
  });
  document.addEventListener("mouseout", (ev) => {
    const from = tipTargetFrom(ev.target);
    if (!from) return;
    const to = tipTargetFrom(ev.relatedTarget);
    if (to === from) return;
    if (to) {
      showFor(to);
      return;
    }
    clearIfLeft(ev.relatedTarget);
  });
  document.addEventListener("focusin", (ev) => {
    showFor(ev.target);
  });
  document.addEventListener("focusout", (ev) => {
    const next = ev.relatedTarget;
    if (next && tipTargetFrom(next)) return;
    activeTipEl = null;
    setTip("Hover a control for help", { idle: true });
  });

  setTip("Hover a control for help", { idle: true });
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  let data = null;
  const text = await res.text();
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }
  if (!res.ok) {
    const detail = data?.detail || res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

function isFileProtocol() {
  return window.location.protocol === "file:";
}

function ensureAudio() {
  if (!audioCtx) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    audioCtx = new Ctx();
  }
  if (audioCtx.state === "suspended") {
    return audioCtx.resume();
  }
  return Promise.resolve();
}

function audioUrl(filePath) {
  return `/api/audio?path=${encodeURIComponent(filePath)}`;
}

async function loadBuffer(filePath) {
  if (!filePath) return null;
  if (bufferCache.has(filePath)) return bufferCache.get(filePath);
  await ensureAudio();
  const res = await fetch(audioUrl(filePath));
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`Could not load audio (${res.status}): ${t.slice(0, 120)}`);
  }
  const arr = await res.arrayBuffer();
  const buf = await audioCtx.decodeAudioData(arr.slice(0));
  bufferCache.set(filePath, buf);
  return buf;
}

function stopAll() {
  if (loopTimer != null) {
    clearTimeout(loopTimer);
    loopTimer = null;
  }
  if (activePulseTimer != null) {
    clearInterval(activePulseTimer);
    activePulseTimer = null;
  }
  if (scheduler.timerId != null) {
    clearInterval(scheduler.timerId);
    scheduler.timerId = null;
  }
  for (const { src } of activeSources) {
    try {
      src.stop();
    } catch {
      /* already stopped */
    }
  }
  activeSources = [];
  for (const g of Object.values(trackGains)) {
    try {
      g.disconnect();
    } catch {
      /* ok */
    }
  }
  trackGains = {};
  isPlaying = false;
  isPlayPending = false;
  if (previewMidiTimer != null) {
    clearTimeout(previewMidiTimer);
    previewMidiTimer = null;
  }
  previewLoopRole = null;
  scheduler.nextStep = 0;
  scheduler.nextNoteTime = 0;
  scheduler.buffers = {};
  scheduler.playable = [];
  scheduler.phraseRoles = {};
  serumStemRoles = {};
  for (const k of Object.keys(serumStemMeta)) delete serumStemMeta[k];
  for (const k of Object.keys(serumRefreshing)) delete serumRefreshing[k];
  for (const k of Object.keys(serumPendingBuffer)) delete serumPendingBuffer[k];
  for (const k of Object.keys(serumPendingJs)) delete serumPendingJs[k];
  for (const k of Object.keys(liveMidiRefreshTimers)) {
    clearTimeout(liveMidiRefreshTimers[k]);
    delete liveMidiRefreshTimers[k];
  }
  if (liveBpmSerumTimer) {
    clearTimeout(liveBpmSerumTimer);
    liveBpmSerumTimer = null;
  }
  liveBpmSerumBusy = false;
  transportBusyCount = 0;
  transportBusyLabel = "";
  clearAllActive();
  updatePlayButton();
  // Keep last peaks visible; playhead freezes at last position
  stopWaveRaf();
}

function anySoloActive() {
  return activeTrackIds().some((r) => state.slots[r]?.solo);
}

/** Audible if not muted, and (no solos active OR this track is soloed). */
function isTrackAudible(role) {
  const s = state.slots[role];
  if (!s || s.muted) return false;
  if (anySoloActive()) return Boolean(s.solo);
  return true;
}

function ensureTrackGain(role) {
  if (!audioCtx) return null;
  if (trackGains[role]) return trackGains[role];
  const g = audioCtx.createGain();
  g.gain.value = isTrackAudible(role) ? 1 : 0;
  g.connect(audioCtx.destination);
  trackGains[role] = g;
  return g;
}

/** Instant mute/solo gain update while playing. */
function applyTrackMute(role) {
  const g = trackGains[role];
  if (!g || !audioCtx) return;
  const audible = isTrackAudible(role);
  const now = audioCtx.currentTime;
  g.gain.cancelScheduledValues(now);
  g.gain.setValueAtTime(audible ? 1 : 0, now);
  const hasContent =
    Boolean(scheduler.buffers[role]) || Boolean(state.slots[role]?.midi?.grid);
  setSlotActive(role, isPlaying && audible && hasContent);
}

/** Recompute all track gains (needed when solo changes — affects every track). */
function applyAllTrackGains() {
  for (const role of activeTrackIds()) {
    if (trackGains[role] || isPlaying) {
      ensureTrackGain(role);
      applyTrackMute(role);
    }
    syncSoloUi(role);
  }
}

/** Name + path + meta for BPM / loop detection (path often has `_140_`). */
function sampleNameBlob(roleOrName) {
  if (roleOrName && state.slots[roleOrName]) {
    const s = state.slots[roleOrName];
    return [s.name, s.path, s.meta].filter(Boolean).join(" ");
  }
  return String(roleOrName || "");
}

/**
 * Long loop / phrase samples must not re-trigger every 16th (stacks on itself).
 * One-shots stay short; loops are multi-beat beds locked to the kick cycle.
 * @param {AudioBuffer | null} buffer
 * @param {string} name  name/path blob
 * @param {string | null} [type]  track type (kick, hats, lead_audio, …)
 */
function isPhraseSample(buffer, name = "", type = null) {
  if (!buffer) return false;
  const n = String(name).toLowerCase();
  const t = String(type || "").toLowerCase();

  // Explicit loop / bed cues (all sample roles: hats, perc, lead_audio, fx, vocal…)
  if (
    /\bloops?\b|_loop|loop_|looper|looped|phrase|screech|top[_-]?loop|full[_-]?loop|drum[_-]?loop|hat[_-]?loop|perc[_-]?loop|melody|melodic|atmosphere|ambient|texture|\bbed\b|groove|construction|stem\b|fill\b/.test(
      n
    )
  ) {
    return true;
  }
  if (/\brolling\b/.test(n) && buffer.duration > 0.8) return true;

  // Filename tempo tag (e.g. _155_) + longer than a one-shot → loop bed
  if (parseBpmFromName(name) && buffer.duration > 0.9) {
    return true;
  }

  const barSec = secPer16th() * 16;
  const isDrum = ["kick", "clap", "snare", "hats", "perc"].includes(t);

  if (isDrum) {
    // Hats/perc tops are often 1-bar loops without "loop" in the name
    if ((t === "hats" || t === "perc") && buffer.duration >= barSec * 0.55) {
      return true;
    }
    // Kick/clap: only multi-bar beds (avoid long one-shot tails)
    return buffer.duration >= barSec * 1.4;
  }

  // lead_audio / vocal / fx / loop / unknown musical samples
  return buffer.duration > Math.max(1.0, barSec * 0.55);
}

/**
 * BPM warp for any sample hit (one-shot or cycle trigger).
 * Only applies when a native BPM is tagged — never stretch pure one-shots by duration.
 */
function sampleBpmWarpOpts(role, buffer) {
  const blob = sampleNameBlob(role);
  const native = parseBpmFromName(blob);
  if (!native) return {};
  return {
    playbackRate: Math.max(0.25, Math.min(4, getBpm() / native)),
    nativeBpm: native,
  };
}

/**
 * Parse native tempo from sample names (Splice-style).
 * e.g. DS_HT_155_drum_kick_lion_rolling_G.wav → 155
 * @returns {number | null}
 */
function parseBpmFromName(name) {
  const s = String(name || "");
  // Explicit "155bpm" / "bpm_140"
  let m =
    s.match(/(?:^|[_\-\s.])(\d{2,3})\s*bpm\b/i) ||
    s.match(/\bbpm[_\-\s.]*(\d{2,3})\b/i);
  if (m) {
    const n = Number(m[1]);
    if (n >= 60 && n <= 200) return n;
  }
  // Underscore/dash-separated number in tempo range (common pack naming)
  const re = /(?:^|[_\-\s.\/\\])(\d{2,3})(?=[_\-\s.\/\\]|$)/g;
  let match;
  while ((match = re.exec(s)) !== null) {
    const n = Number(match[1]);
    if (n >= 70 && n <= 200) return n;
  }
  return null;
}

/**
 * playbackRate so a loop matches session BPM.
 * 1) Prefer BPM tag in name/path
 * 2) Else stretch so buffer duration ≈ nearest whole bars (keeps hats on the kick grid)
 */
function phrasePlaybackFor(buffer, roleOrName) {
  const blob = sampleNameBlob(roleOrName);
  const native = parseBpmFromName(blob);
  const session = getBpm();
  if (native) {
    return {
      rate: Math.max(0.25, Math.min(4, session / native)),
      nativeBpm: native,
    };
  }
  if (!buffer || !(buffer.duration > 0.05)) {
    return { rate: 1, nativeBpm: null };
  }
  const barSec = secPer16th() * 16;
  // Nearest 1..LOOP_BARS bars of wall-clock at session tempo
  let bars = Math.round(buffer.duration / barSec);
  if (!Number.isFinite(bars) || bars < 1) bars = 1;
  if (bars > LOOP_BARS) bars = LOOP_BARS;
  const targetSec = bars * barSec;
  const rate = Math.max(0.25, Math.min(4, buffer.duration / targetSec));
  return { rate, nativeBpm: null };
}

/** @deprecated use phrasePlaybackFor */
function warpRateForName(name) {
  const native = parseBpmFromName(name);
  if (!native) return { rate: 1, nativeBpm: null };
  const session = getBpm();
  return { rate: session / native, nativeBpm: native };
}

/**
 * @param {AudioBuffer} buffer
 * @param {number} when
 * @param {number} gainValue
 * @param {string | null} role  if set, route through live-muteable track bus
 * @param {{ loop?: boolean, stopAt?: number, playbackRate?: number, nativeBpm?: number|null, offsetSec?: number, durationSec?: number }} [opts]
 */
function scheduleBuffer(buffer, when, gainValue = 1, role = null, opts = {}) {
  if (!audioCtx || !buffer) return;
  const src = audioCtx.createBufferSource();
  const gain = audioCtx.createGain();
  src.buffer = buffer;
  gain.gain.value = gainValue;

  // Web Audio: start(when) with when < currentTime skips into the buffer by the
  // lateness amount — that chops kick/sample transients. Clamp to "now" instead.
  // Mid-cycle Serum seeks (offset > 0) absorb lateness into the offset so phase stays locked.
  let startWhen = Number(when) || 0;
  let offset =
    opts.offsetSec != null && Number.isFinite(opts.offsetSec)
      ? Math.max(0, Math.min(buffer.duration - 0.001, opts.offsetSec))
      : 0;
  const now = audioCtx.currentTime;
  if (startWhen < now) {
    const late = now - startWhen;
    if (offset > 0) {
      offset = Math.min(buffer.duration - 0.001, offset + late);
    }
    startWhen = now;
  }

  const rate =
    opts.playbackRate != null && Number.isFinite(opts.playbackRate)
      ? Math.max(0.25, Math.min(4, opts.playbackRate))
      : 1;
  src.playbackRate.setValueAtTime(rate, startWhen);
  src.connect(gain);
  if (role) {
    const bus = ensureTrackGain(role);
    if (bus) gain.connect(bus);
    else gain.connect(audioCtx.destination);
  } else {
    gain.connect(audioCtx.destination);
  }
  if (opts.loop) {
    src.loop = true;
  }
  const durOpt =
    opts.durationSec != null && Number.isFinite(opts.durationSec)
      ? Math.max(0.02, opts.durationSec)
      : undefined;
  try {
    if (durOpt != null) src.start(startWhen, offset, durOpt);
    else if (offset > 0) src.start(startWhen, offset);
    else src.start(startWhen);
  } catch {
    try {
      src.start(startWhen);
    } catch {
      /* ok */
    }
  }
  if (opts.stopAt != null && opts.stopAt > startWhen) {
    try {
      src.stop(opts.stopAt);
    } catch {
      /* ok */
    }
  }
  activeSources.push({
    src,
    gain,
    role,
    nativeBpm: opts.nativeBpm != null ? opts.nativeBpm : null,
  });
  src.onended = () => {
    activeSources = activeSources.filter((s) => s.src !== src);
  };
}

function setSlotActive(role, on) {
  const el = $(`.slot[data-role="${role}"]`);
  el?.classList.toggle("active", Boolean(on));
}

function clearAllActive() {
  $all(".slot.active").forEach((el) => el.classList.remove("active"));
}

function syncPreviewBtn(role) {
  const slot = ensureSlotEl(role);
  if (!slot) return;
  const btn =
    $(".icon-btn.preview", slot) ||
    $all(".icon-btn", slot).find((b) => b.getAttribute("aria-label") === "Preview");
  if (!btn) return;
  const on = previewLoopRole === role;
  btn.classList.toggle("on", on);
  btn.setAttribute("aria-pressed", String(on));
  btn.textContent = on ? "⏹" : "▶";
  btn.dataset.tip = on
    ? "Stop this track’s loop"
    : isSerumTrack(role)
      ? "Loop MIDI preview (toggle to stop)"
      : "Loop this sample (toggle to stop)";
}

function scheduleMidiPreviewBar(role, when) {
  if (!window.MidiEngine) return;
  const s = state.slots[role];
  if (!s?.midi?.grid) return;
  const key = $("#key")?.value || "F minor";
  const step16 = secPer16th();
  const notes = MidiEngine.gridToNotes(s.midi.grid, key, s.midi.octave, 1);
  for (const n of notes) {
    scheduleSynthNote(
      n.midi,
      when + n.step * step16,
      Math.max(0.05, n.duration * step16 * 0.95),
      role,
      n.vel
    );
  }
}

/** Arm next MIDI preview bar (BPM-live). */
function armMidiPreviewLoop(role) {
  if (previewLoopRole !== role || !audioCtx) return;
  const barSec = secPer16th() * 16;
  const t0 = audioCtx.currentTime + 0.03;
  scheduleMidiPreviewBar(role, t0);
  if (previewMidiTimer != null) clearTimeout(previewMidiTimer);
  previewMidiTimer = setTimeout(() => armMidiPreviewLoop(role), barSec * 1000);
}

/**
 * Per-track ▶ : toggle loop for that track only. Click again to stop.
 */
async function previewSlot(role) {
  // Toggle off if this track is already looping
  if (previewLoopRole === role) {
    previewGen += 1;
    stopAll();
    setStatus(`Stopped · ${role}`);
    return;
  }

  const s = state.slots[role];
  if (!s) {
    setStatus(`${role}: nothing to play`);
    return;
  }
  if (s.muted) {
    setStatus(`${role} is muted — unmute to preview`);
    return;
  }

  const gen = ++previewGen;
  const isSerum = isSerumTrack(role) || s.kind === "serum";
  if (isSerum) {
    if (!s.midi?.grid || !window.MidiEngine) {
      setStatus(`${role}: no MIDI yet — open M to edit a pattern`);
      return;
    }
    try {
      stopAll();
      if (gen !== previewGen) return;
      await ensureAudio();
      if (gen !== previewGen) return;
      previewLoopRole = role;
      ensureTrackGain(role);
      applyTrackMute(role);
      setSlotActive(role, true);
      syncPreviewBtn(role);
      armMidiPreviewLoop(role);
      setStatus(`Looping MIDI · ${role} @ ${getBpm()} BPM · click ⏹ to stop`);
    } catch (e) {
      if (gen === previewGen) {
        previewLoopRole = null;
        setStatus(`MIDI preview failed: ${e.message}`);
      }
    }
    return;
  }

  if (s.empty || !s.path) {
    setStatus(`${role}: nothing to play`);
    return;
  }
  try {
    stopAll();
    if (gen !== previewGen) return;
    await ensureAudio();
    if (gen !== previewGen) return;
    const buf = await loadBuffer(s.path);
    if (gen !== previewGen) return;
    previewLoopRole = role;
    setSlotActive(role, true);
    ensureTrackGain(role);
    applyTrackMute(role);
    {
      const { rate, nativeBpm } = phrasePlaybackFor(buf, role);
      scheduleBuffer(buf, audioCtx.currentTime + 0.02, SLOT_GAIN[role] ?? 0.8, role, {
        loop: true,
        playbackRate: rate,
        nativeBpm,
      });
    }
    syncPreviewBtn(role);
    setStatus(`Looping ${role}: ${s.name} · click ⏹ to stop`);
  } catch (e) {
    if (gen === previewGen) {
      previewLoopRole = null;
      setStatus(`Preview failed (${role}): ${e.message}`);
    }
  }
}

/**
 * Cheap monophonic synth so MIDI is audible without Serum.
 * Routes through track gain → mute still works live.
 */
function scheduleSynthNote(midi, when, durationSec, role, vel = 100) {
  if (!audioCtx || durationSec <= 0) return;
  // Same past-start issue as samples — don't start oscillators in the past
  if (when < audioCtx.currentTime) when = audioCtx.currentTime;
  const bus = ensureTrackGain(role);
  const osc = audioCtx.createOscillator();
  const filt = audioCtx.createBiquadFilter();
  const gain = audioCtx.createGain();

  const t = baseType(role);
  osc.type = t === "bass" ? "triangle" : "sawtooth";
  const freq = 440 * Math.pow(2, (midi - 69) / 12);
  osc.frequency.setValueAtTime(freq, when);

  filt.type = "lowpass";
  filt.frequency.setValueAtTime(t === "bass" ? 600 : 2800, when);
  filt.Q.setValueAtTime(0.7, when);

  const peak = (vel / 127) * (t === "bass" ? 0.4 : 0.22);
  const attack = 0.008;
  const release = Math.min(0.08, durationSec * 0.25);
  const end = when + durationSec;

  gain.gain.setValueAtTime(0.0001, when);
  gain.gain.exponentialRampToValueAtTime(Math.max(peak, 0.001), when + attack);
  gain.gain.setValueAtTime(peak, Math.max(when + attack, end - release));
  gain.gain.exponentialRampToValueAtTime(0.0001, end);

  osc.connect(filt);
  filt.connect(gain);
  if (bus) gain.connect(bus);
  else gain.connect(audioCtx.destination);

  osc.start(when);
  osc.stop(end + 0.02);
  activeSources.push({ src: osc, gain });
  osc.onended = () => {
    activeSources = activeSources.filter((s) => s.src !== osc);
  };
}

function scheduleMidiAtStep(step, when) {
  if (!window.MidiEngine) return;
  const key = $("#key")?.value || "F minor";
  const step16 = secPer16th();

  for (const role of activeTrackIds()) {
    if (!isSerumTrack(role)) continue;
    // Real Serum stem already playing (or mid re-bounce after dice)
    if (serumStemRoles[role] || serumRefreshing[role]) continue;
    const midiState = state.slots[role]?.midi;
    if (!midiState?.grid) continue;
    // Mute via track gain; still schedule so unmute mid-note works for future notes
    const barStep = step % 16;
    const cell = midiState.grid[barStep];
    if (!cell) continue;
    const t = baseType(role);
    const oct = midiState.octave ?? MidiEngine.defaultOctave(t === "bass" ? "bass" : "lead");
    const note = MidiEngine.degreeToMidi(key, cell.degree, oct);
    const dur = Math.max(0.05, (cell.length || 1) * step16 * 0.95);
    scheduleSynthNote(note, when, dur, role, cell.vel ?? 100);
  }
}

/** Stop any currently scheduled/playing sources for one track (live dice swap). */
function stopSourcesForRole(role) {
  if (!role) return;
  const keep = [];
  for (const entry of activeSources) {
    if (entry.role === role) {
      try {
        entry.src.stop();
      } catch {
        /* already stopped */
      }
    } else {
      keep.push(entry);
    }
  }
  activeSources = keep;
}

/**
 * Loop cycle length in 16th steps.
 */
function serumCycleSteps() {
  return scheduler.totalSteps || LOOP_BARS * 16;
}

/**
 * Pending live cutovers — applied only inside scheduleStep so Serum shares
 * the exact same AudioContext time as the kick for that step.
 * @type {Record<string, { buf: AudioBuffer, gen: number }>}
 */
const serumPendingBuffer = {};

/** Switch this role to JS synth on the next grid tick (not mid-step). */
/** @type {Record<string, boolean>} */
const serumPendingJs = {};

/**
 * Seek offset into a full-cycle bounce for a given step index.
 * Uses buffer duration so phase matches the rendered timeline.
 */
function serumOffsetForStep(buffer, stepInCycle) {
  const cycle = serumCycleSteps();
  if (!buffer || cycle <= 0) return 0;
  const step = ((stepInCycle % cycle) + cycle) % cycle;
  if (step <= 0) return 0;
  return Math.min(buffer.duration * 0.999, (step / cycle) * buffer.duration);
}

/**
 * Fire one offline-rendered Serum stem locked to the kick/grid.
 *
 * Stems are bounced offline at a specific BPM at rate ~1 (pitch-correct).
 * `offsetSec` seeks into the bounce so mid-cycle updates stay phase-locked
 * to kicks. Call with the same `when` as the kick for that step.
 */
function scheduleSerumStemRole(role, when, opts = {}) {
  if (serumRefreshing[role]) return; // live dice: don't re-arm old/missing stem
  const buffer = scheduler.buffers[role];
  if (!buffer || !serumStemRoles[role]) return;

  // Never play a bounce recorded at a different BPM (notes stay at old tempo).
  const meta = serumStemMeta[role];
  const sessionBpm = getBpm();
  if (
    meta?.stale ||
    (meta?.bpm != null && Math.abs(meta.bpm - sessionBpm) > 0.25)
  ) {
    scheduleSerumRefreshForNewBpm();
    return;
  }

  const cycle = serumCycleSteps();
  const cycleSec = cycle * secPer16th();
  if (cycleSec <= 0) return;
  const t = baseType(role);
  const g = SLOT_GAIN[t] ?? 0.7;
  // Unity rate keeps pitch; length should match cycle when bounce BPM == session BPM.
  let rate = 1;
  if (buffer.duration > 0.05) {
    const ratio = buffer.duration / cycleSec;
    if (ratio > 0.97 && ratio < 1.03) {
      rate = ratio;
    }
  }
  const offsetSec =
    opts.offsetSec != null && Number.isFinite(opts.offsetSec)
      ? Math.max(0, opts.offsetSec)
      : 0;
  // Remaining wall-clock time until next cycle boundary (kick-aligned)
  const stepIn =
    opts.stepIn != null
      ? opts.stepIn
      : Math.round((offsetSec / Math.max(buffer.duration, 1e-6)) * cycle);
  const remainSteps = Math.max(1, cycle - (((stepIn % cycle) + cycle) % cycle));
  const remainSec = remainSteps * secPer16th();
  // Only cut previous when explicitly live-cutting (not when look-ahead
  // pre-schedules the next cycle — that would silence the last ~150ms).
  if (opts.cutPrevious) stopSourcesForRole(role);
  scheduleBuffer(buffer, when, g, role, {
    loop: false,
    stopAt: when + remainSec + 0.02,
    playbackRate: rate,
    offsetSec,
    durationSec: remainSec / rate,
  });
}

/**
 * Queue a new bounce to start on the next transport step (same clock as kick).
 */
function queueSerumBufferCutover(role, buf, gen) {
  if (!buf || !role) return;
  serumPendingBuffer[role] = { buf, gen };
}

/**
 * Apply any pending Serum buffers / JS switches at this exact grid time.
 * Must run before kicks + MIDI so everything shares `when`.
 * @returns {Set<string>} roles that already started a stem this step
 */
function applyPendingSerumAtStep(step, when) {
  const cycle = serumCycleSteps();
  const stepIn = ((step % cycle) + cycle) % cycle;
  /** @type {Set<string>} */
  const started = new Set();

  // Deferred JS preview: drop stem on a step boundary, then MIDI fires this step
  for (const role of Object.keys(serumPendingJs)) {
    if (!serumPendingJs[role]) continue;
    if (serumStemRoles[role]) {
      stopSourcesForRole(role);
      delete serumStemRoles[role];
    }
    delete serumPendingJs[role];
  }

  // Deferred real-stem cutover (after bounce finished mid-loop)
  for (const role of Object.keys(serumPendingBuffer)) {
    const pending = serumPendingBuffer[role];
    if (!pending?.buf) {
      delete serumPendingBuffer[role];
      continue;
    }
    // Drop if a newer refresh superseded this buffer
    if (
      pending.gen != null &&
      trackRefreshGen[role] != null &&
      pending.gen !== trackRefreshGen[role]
    ) {
      delete serumPendingBuffer[role];
      continue;
    }
    scheduler.buffers[role] = pending.buf;
    markWaveDirty();
    serumStemRoles[role] = true;
    serumStemMeta[role] = { bpm: getBpm(), stale: false };
    if (!scheduler.playable.includes(role)) scheduler.playable.push(role);
    ensureTrackGain(role);
    applyTrackMute(role);
    serumRefreshing[role] = false;
    const offsetSec = serumOffsetForStep(pending.buf, stepIn);
    scheduleSerumStemRole(role, when, {
      offsetSec,
      stepIn,
      cutPrevious: true,
    });
    started.add(role);
    delete serumPendingBuffer[role];
    delete serumPendingJs[role];
  }
  return started;
}

/**
 * Fire offline-rendered Serum stems locked to the transport grid.
 * Re-triggers every cycle so they stay in phase with kicks.
 * @param {number} when
 * @param {Set<string>} [skipRoles] already started this step via live cutover
 */
function scheduleSerumStemsAt(when, skipRoles = null) {
  for (const role of Object.keys(serumStemRoles)) {
    if (skipRoles && skipRoles.has(role)) continue;
    scheduleSerumStemRole(role, when);
  }
}

function scheduleStep(step, when) {
  const stepInBar = step % 16;
  const cycle = serumCycleSteps();

  // Live MIDI/dice cutovers — same `when` as kick for this step
  const startedLive = applyPendingSerumAtStep(step, when);

  // MIDI synth voices — always try, independent of sample buffers
  scheduleMidiAtStep(step, when);

  // Serum stems + sample phrase beds: re-lock to kick grid every cycle
  if (step % cycle === 0) {
    scheduleSerumStemsAt(when, startedLive);
    // cutPrevious on later cycles only — first cycle already started in startPhraseBeds
    if (step > 0) schedulePhraseBedsAt(when, { cutPrevious: true });
  }

  for (const role of scheduler.playable) {
    const buffer = scheduler.buffers[role];
    if (!buffer) continue;
    // Phrase/loop beds & serum stems handled separately
    if (scheduler.phraseRoles[role] || serumStemRoles[role]) continue;

    // Still schedule muted tracks (gain bus is 0) so unmute is instant.
    const t = baseType(role);
    const warp = sampleBpmWarpOpts(role, buffer);
    if (t === "fx" || t === "vocal") {
      // One shot per cycle (or full bed if classified as phrase above)
      if (step % cycle === 0) {
        scheduleBuffer(buffer, when, SLOT_GAIN[t] ?? 0.5, role, warp);
      }
      continue;
    }
    const pat = PATTERNS[t];
    if (pat && pat[stepInBar]) {
      let g = SLOT_GAIN[t] ?? 0.7;
      if (t === "hats" && stepInBar % 2 === 1) g *= 0.65;
      scheduleBuffer(buffer, when, g, role, warp);
    } else if (!pat && step % cycle === 0) {
      // Unknown sample types (e.g. "loop"): fire once per cycle with BPM warp
      scheduleBuffer(buffer, when, SLOT_GAIN[t] ?? 0.6, role, {
        ...warp,
        loop: Boolean(parseBpmFromName(sampleNameBlob(role))),
      });
    }
  }
}

/**
 * Sample phrase beds (hat loops, etc.): warp to session tempo and re-lock on the
 * kick cycle — free-running WebAudio loops drift when BPM tag is missing/wrong.
 * @param {number} when
 * @param {{ cutPrevious?: boolean }} [opts]
 */
function schedulePhraseBedsAt(when, opts = {}) {
  const cutPrevious = opts.cutPrevious !== false;
  for (const role of Object.keys(scheduler.phraseRoles)) {
    if (serumStemRoles[role]) continue; // transport-scheduled stems, not free beds
    const buffer = scheduler.buffers[role];
    if (!buffer) continue;
    if (cutPrevious) stopSourcesForRole(role);
    const t = baseType(role);
    const g = SLOT_GAIN[t] ?? SLOT_GAIN[role] ?? 0.7;
    const { rate, nativeBpm } = phrasePlaybackFor(buffer, role);
    scheduleBuffer(buffer, when, g, role, {
      loop: true,
      playbackRate: rate,
      nativeBpm,
    });
  }
}

/** First play: start beds on the same clock as the first kick. */
function startPhraseBeds(t0) {
  schedulePhraseBedsAt(t0, { cutPrevious: false });
}

/** Update warp rates when session BPM changes mid-play. */
function retuneWarpedSources() {
  if (!audioCtx || !isPlaying) return;
  const now = audioCtx.currentTime;
  for (const entry of activeSources) {
    if (!entry.src?.playbackRate) continue;
    let rate = null;
    if (entry.role && scheduler.phraseRoles[entry.role] && !serumStemRoles[entry.role]) {
      const buf = scheduler.buffers[entry.role];
      if (buf) rate = phrasePlaybackFor(buf, entry.role).rate;
    } else if (entry.nativeBpm) {
      rate = Math.max(0.25, Math.min(4, getBpm() / entry.nativeBpm));
    }
    if (rate == null || !Number.isFinite(rate)) continue;
    try {
      entry.src.playbackRate.cancelScheduledValues(now);
      entry.src.playbackRate.setValueAtTime(rate, now);
    } catch {
      /* ok */
    }
  }
}

function schedulerTick() {
  if (!isPlaying || !audioCtx) return;

  const horizon = audioCtx.currentTime + LOOKAHEAD_SEC;
  // Spacing for *upcoming* steps always uses the current BPM control.
  // Steps keep advancing forever — patterns wrap via step % 16 / totalSteps.
  while (scheduler.nextNoteTime < horizon) {
    scheduleStep(scheduler.nextStep, scheduler.nextNoteTime);
    scheduler.nextStep += 1;
    scheduler.nextNoteTime += secPer16th();
  }
}

/** Roles that already have a bounced Serum stem for this play — skip JS synth. */
let serumStemRoles = {};

/**
 * BPM each stem was offline-bounced at. Stems are NOT time-stretchable without
 * pitch shift — if session BPM differs, buffer is stale until re-render.
 * @type {Record<string, { bpm: number, stale?: boolean }>}
 */
const serumStemMeta = {};

/**
 * While true, scheduler must not re-fire the old stem for this role
 * (dice/live refresh in flight — render can take several seconds).
 * @type {Record<string, boolean>}
 */
const serumRefreshing = {};

/** Bumps per-role when live-refreshing so stale renders are dropped. */
/** @type {Record<string, number>} */
const trackRefreshGen = {};

/** Debounce timers for live MIDI → Serum re-bounce while transport is running. */
/** @type {Record<string, ReturnType<typeof setTimeout>>} */
const liveMidiRefreshTimers = {};

/**
 * Re-render Serum stem after MIDI/octave/macro edits while playing.
 * Debounced so scrubbing octave / clicking many cells doesn't spam the host.
 */
function scheduleLiveSerumRefresh(role, { delayMs = 120 } = {}) {
  if (!role || !isPlaying || !isSerumTrack(role)) return;
  const s = state.slots[role];
  if (!s?.midi?.grid || !s.path) return;
  const pl = String(s.path).toLowerCase();
  if (!pl.endsWith(".fxp") && !pl.endsWith(".serumpreset")) return;

  // Instant feedback: JS synth follows the new MIDI while bounce runs
  beginProvisionalJsSynth(role);

  if (liveMidiRefreshTimers[role]) {
    clearTimeout(liveMidiRefreshTimers[role]);
  }
  liveMidiRefreshTimers[role] = setTimeout(() => {
    liveMidiRefreshTimers[role] = null;
    if (!isPlaying || !state.slots[role]?.midi) return;
    refreshPlayingTrack(role, { provisionalJs: true, keepOldUntilReady: false }).catch(
      (e) => console.warn(`live MIDI refresh ${role}:`, e)
    );
  }, delayMs);
}

/**
 * Request JS-synth preview on the *next* grid tick (not mid-step).
 * Avoids restarting audio off the kick clock.
 */
function beginProvisionalJsSynth(role) {
  if (!isPlaying || !isSerumTrack(role)) return;
  serumPendingJs[role] = true;
  if (serumStemMeta[role]) serumStemMeta[role].stale = true;
}

/**
 * Offline-render one Serum track. Returns AudioBuffer or null.
 * @param {string} role
 * @param {{ quiet?: boolean }} [opts]
 */
async function renderOneSerumStem(role, opts = {}) {
  if (!isSerumTrack(role)) return null;
  const s = state.slots[role];
  if (!s?.midi?.grid || !s.path) return null;
  // Any .fxp / .SerumPreset path is a host bounce candidate
  const pl = String(s.path).toLowerCase();
  if (!pl.endsWith(".fxp") && !pl.endsWith(".serumpreset")) return null;

  const bpm = getBpm();
  const key = $("#key")?.value || "F minor";
  const bars = scheduler.bars || LOOP_BARS;
  if (!opts.quiet) setStatus(`Rendering Serum · ${role}…`);

  const payload = {
    role,
    bpm,
    bars,
    key,
    octave: s.midi.octave ?? (baseType(role) === "bass" ? 2 : 4),
    fxp: s.path,
    grid: s.midi.grid,
  };
  // Applied macros (Serum1: 4, Serum2: up to 8 — host normalizes)
  if (Array.isArray(s.macros) && s.macros.length) {
    payload.macros = s.macros.slice(0, 8);
  }
  beginTransportBusy(`Rendering ${role}…`);
  try {
    const result = await api("/api/serum/render", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (!result.url) return null;
    // fxp_loaded false on a cold render means init/default Serum was bounced under this path
    if (result.fxp_loaded === false) {
      console.warn(`Serum ${role}: preset failed to load · ${s.path}`);
      if (!opts.quiet) {
        setStatus(`Serum preset failed to load · ${role} · check host / path`);
      }
      return null;
    }
    const buf = await loadBufferUrl(result.url, { bust: true });
    if (buf) {
      console.info(
        `Serum ${role}: fxp_loaded=${result.fxp_loaded} peak=${result.peak} cached=${result.cached} path=${s.path}`
      );
    }
    return buf || null;
  } finally {
    endTransportBusy();
  }
}

/**
 * Offline-render bass/lead through DawDreamer + real preset (Python 3.12 host).
 * Returns map role -> AudioBuffer (or empty on failure).
 */
async function renderSerumStems() {
  const out = {};
  const bpm = getBpm();
  const failed = [];
  for (const role of activeTrackIds()) {
    if (!isSerumTrack(role)) continue;
    try {
      const buf = await renderOneSerumStem(role);
      if (buf) {
        out[role] = buf;
        serumStemRoles[role] = true;
        serumStemMeta[role] = { bpm, stale: false };
      } else if (state.slots[role]?.path && state.slots[role]?.midi?.grid) {
        failed.push(role);
      }
    } catch (e) {
      console.warn(`Serum render ${role} failed, using JS synth:`, e);
      failed.push(role);
    }
  }
  if (failed.length) {
    setStatus(
      `Serum bounce failed · ${failed.join(", ")} · JS synth fallback (same tone until host recovers)`
    );
  }
  return out;
}

/**
 * After dice / path / MIDI / BPM change while transport is running.
 * @param {{ provisionalJs?: boolean, keepOldUntilReady?: boolean }} [opts]
 *  - provisionalJs: already on JS synth; swap to real stem when ready
 *  - keepOldUntilReady: keep previous stem audible until new bounce arrives (dice)
 */
async function refreshPlayingTrack(role, opts = {}) {
  // isPlayPending: still loading first play — skip; isPlaying: live transport
  if (!isPlaying || !audioCtx || !role) return;
  const gen = (trackRefreshGen[role] = (trackRefreshGen[role] || 0) + 1);
  const mine = gen;
  const keepOld = opts.keepOldUntilReady !== false && !opts.provisionalJs;

  const s = state.slots[role];
  if (!s || s.empty || !s.path) {
    serumRefreshing[role] = false;
    stopSourcesForRole(role);
    delete scheduler.buffers[role];
    delete serumStemRoles[role];
    delete scheduler.phraseRoles[role];
    scheduler.playable = scheduler.playable.filter((r) => r !== role);
    return;
  }

  const isSerum =
    isSerumTrack(role) ||
    s.kind === "serum" ||
    /\.(fxp|serumpreset)$/i.test(String(s.path || ""));

  try {
    if (isSerum) {
      if (keepOld) {
        // Dice / BPM: leave old audio running; don't block cycle with serumRefreshing
        setStatus(`Updating Serum · ${role}…`);
      } else if (opts.provisionalJs) {
        // MIDI path already switched to JS synth
        setStatus(`Serum bounce · ${role}…`);
      } else {
        serumRefreshing[role] = true;
        stopSourcesForRole(role);
        delete scheduler.buffers[role];
        delete scheduler.phraseRoles[role];
        setStatus(`Updating Serum · ${role}…`);
      }

      let buf = null;
      let errMsg = "";
      try {
        buf = await renderOneSerumStem(role, { quiet: true });
      } catch (e) {
        errMsg = String(e.message || e);
        console.warn(`Live Serum refresh ${role} failed:`, e);
      }

      if (mine !== trackRefreshGen[role]) return;
      if (!isPlaying) {
        serumRefreshing[role] = false;
        return;
      }

      if (buf) {
        // Queue for next scheduleStep — same AudioContext time as the kick
        queueSerumBufferCutover(role, buf, mine);
        serumRefreshing[role] = false;
        setStatus(
          `Live · ${role} · ${s.name || "new preset"} · ${getBpm()} BPM · sync on grid`
        );
      } else {
        serumRefreshing[role] = false;
        if (!keepOld) {
          delete serumStemRoles[role];
          delete serumStemMeta[role];
          delete scheduler.buffers[role];
          scheduler.playable = scheduler.playable.filter((r) => r !== role);
        }
        ensureTrackGain(role);
        applyTrackMute(role);
        setStatus(
          errMsg
            ? `Serum render failed · ${role}: ${errMsg}`
            : `Serum · ${role} · JS synth fallback`
        );
      }
      return;
    }

    // Sample tracks
    stopSourcesForRole(role);
    setStatus(`Updating sample · ${role}…`);
    const buf = await loadBuffer(s.path);
    if (mine !== trackRefreshGen[role] || !isPlaying) return;
    if (!buf) return;
    stopSourcesForRole(role);
    scheduler.buffers[role] = buf;
    markWaveDirty();
    if (!scheduler.playable.includes(role)) scheduler.playable.push(role);
    ensureTrackGain(role);
    applyTrackMute(role);
    const blob = sampleNameBlob(role);
    const t = baseType(role);
    if (isPhraseSample(buf, blob, t)) {
      scheduler.phraseRoles[role] = true;
      // Kick-lock on next cycle boundary (avoid mid-bar free-run drift)
      const g = SLOT_GAIN[t] ?? 0.7;
      const { rate, nativeBpm } = phrasePlaybackFor(buf, role);
      // Immediate preview, then cycle re-lock keeps phase with kick
      scheduleBuffer(buf, audioCtx.currentTime + 0.02, g, role, {
        loop: true,
        playbackRate: rate,
        nativeBpm,
      });
    } else {
      delete scheduler.phraseRoles[role];
    }
  } catch (e) {
    serumRefreshing[role] = false;
    console.warn(`refreshPlayingTrack ${role}:`, e);
    setStatus(`Live update failed · ${role}: ${e.message || e}`);
  }
}

async function loadBufferUrl(url, opts = {}) {
  await ensureAudio();
  let fetchUrl = url;
  if (opts.bust) {
    fetchUrl += (url.includes("?") ? "&" : "?") + `_=${Date.now()}`;
  }
  const res = await fetch(fetchUrl, { cache: "no-store" });
  if (!res.ok) throw new Error(`audio ${res.status}`);
  const arr = await res.arrayBuffer();
  return audioCtx.decodeAudioData(arr.slice(0));
}

/**
 * Play looping transport with a look-ahead scheduler (repeats until stop).
 * BPM is read continuously — change the BPM control while playing and tempo follows.
 * Bass/lead: real Serum bounce when host available; else built-in synth.
 */
async function playLoop() {
  // Soft-reset audio graph without clearing the pending toggle state
  if (loopTimer != null) {
    clearTimeout(loopTimer);
    loopTimer = null;
  }
  if (scheduler.timerId != null) {
    clearInterval(scheduler.timerId);
    scheduler.timerId = null;
  }
  for (const { src } of activeSources) {
    try {
      src.stop();
    } catch {
      /* already stopped */
    }
  }
  activeSources = [];
  for (const g of Object.values(trackGains)) {
    try {
      g.disconnect();
    } catch {
      /* ok */
    }
  }
  trackGains = {};
  isPlaying = false;
  clearAllActive();

  serumStemRoles = {};
  for (const k of Object.keys(serumStemMeta)) delete serumStemMeta[k];
  for (const k of Object.keys(serumRefreshing)) delete serumRefreshing[k];
  for (const k of Object.keys(serumPendingBuffer)) delete serumPendingBuffer[k];
  for (const k of Object.keys(serumPendingJs)) delete serumPendingJs[k];
  await ensureAudio();

  // User hit stop while we were loading
  if (!isPlayPending) return;

  const buffers = {};
  const loadNotes = [];

  for (const role of activeTrackIds()) {
    const s = state.slots[role];
    // Load muted tracks too so mute/unmute works live mid-loop.
    if (!s || s.empty || !s.path || isSerumTrack(role) || s.kind === "serum") continue;
    loadNotes.push(
      loadBuffer(s.path)
        .then((buf) => {
          buffers[role] = buf;
        })
        .catch((e) => {
          console.warn(role, e);
        })
    );
  }

  setStatus("Loading samples…");
  beginTransportBusy("Loading samples…");
  try {
    await Promise.all(loadNotes);
  } finally {
    endTransportBusy();
  }
  if (!isPlayPending) return;

  // Real Serum stems (async host) — each renderOneSerumStem also marks busy
  let serumBuffers = {};
  try {
    serumBuffers = await renderSerumStems();
  } catch (e) {
    console.warn(e);
  }
  if (!isPlayPending) return;

  for (const [role, buf] of Object.entries(serumBuffers)) {
    buffers[role] = buf;
  }

  const playable = Object.keys(buffers);
  const midiRoles = activeTrackIds().filter(
    (r) => isSerumTrack(r) && state.slots[r]?.midi?.grid
  );
  if (!playable.length && !midiRoles.length) {
    isPlayPending = false;
    updatePlayButton();
    setStatus("Nothing to play — no samples or MIDI.");
    return;
  }

  scheduler.buffers = buffers;
  scheduler.playable = playable;
  scheduler.phraseRoles = {};
  for (const role of playable) {
    const blob = sampleNameBlob(role);
    // Sample loops (hats, perc, lead beds, fx…): re-lock on transport like Serum
    if (
      !serumStemRoles[role] &&
      isPhraseSample(buffers[role], blob, baseType(role))
    ) {
      scheduler.phraseRoles[role] = true;
    }
  }
  scheduler.nextStep = 0;
  scheduler.totalSteps = scheduler.bars * 16;

  isPlaying = true;
  isPlayPending = false;
  updatePlayButton();
  clearAllActive();
  for (const role of playable) {
    ensureTrackGain(role);
    applyTrackMute(role);
  }
  for (const role of midiRoles) {
    ensureTrackGain(role);
    applyTrackMute(role);
    if (isTrackAudible(role)) setSlotActive(role, true);
  }

  // Arm the clock *after* graph setup so lead time isn't eaten (past start
  // times skip into buffers and chop kick transients).
  scheduler.nextNoteTime = audioCtx.currentTime + START_LEAD_SEC;
  // Long loops + Serum stems: one start (buffer-loop). Short one-shots: pattern steps.
  startPhraseBeds(scheduler.nextNoteTime);
  schedulerTick();
  scheduler.timerId = setInterval(schedulerTick, SCHEDULE_MS);

  waveView.lastProgress = 0;
  markWaveDirty();
  startWaveRaf();

  const phrases = Object.keys(scheduler.phraseRoles);
  const serumRoles = Object.keys(serumStemRoles);
  let line = playingStatusLine();
  if (phrases.length) line += ` · beds: ${phrases.join(", ")}`;
  if (serumRoles.length) line += ` · Serum: ${serumRoles.join(", ")}`;
  else if (midiRoles.length) line += ` · JS synth MIDI (host offline)`;
  setStatus(line);
}

/** Play button = toggle: start looping, or stop if already running/loading. */
function togglePlay() {
  if (isPlaying || isPlayPending) {
    stopAll();
    setStatus("Stopped");
    return;
  }
  isPlayPending = true;
  updatePlayButton();
  playLoop().catch((e) => {
    isPlayPending = false;
    isPlaying = false;
    updatePlayButton();
    setStatus(`Play failed: ${e.message}`);
  });
}

/** Debounce re-bounce of all Serum stems when session BPM changes mid-play. */
let liveBpmSerumTimer = null;
/** Prevent overlapping full-stack BPM re-renders. */
let liveBpmSerumBusy = false;

function serumRolesNeedingBounce() {
  return activeTrackIds().filter((role) => {
    if (!isSerumTrack(role)) return false;
    const s = state.slots[role];
    if (!s?.path || !s?.midi?.grid) return false;
    const pl = String(s.path).toLowerCase();
    return pl.endsWith(".fxp") || pl.endsWith(".serumpreset");
  });
}

/** Stop old-tempo stems; JS synth covers on next grid tick until re-bounce. */
function invalidateSerumStemsForBpmChange() {
  for (const role of serumRolesNeedingBounce()) {
    serumPendingJs[role] = true; // switch on next step (kick-aligned)
    serumStemMeta[role] = { bpm: 0, stale: true };
    delete serumPendingBuffer[role];
  }
}

/**
 * Re-bounce every Serum track at the current session BPM (serial — host is flaky
 * if multiple Serum processes run at once).
 */
function scheduleSerumRefreshForNewBpm() {
  if (!isPlaying) return;
  const roles = serumRolesNeedingBounce();
  if (!roles.length) return;
  if (liveBpmSerumTimer) clearTimeout(liveBpmSerumTimer);
  liveBpmSerumTimer = setTimeout(() => {
    liveBpmSerumTimer = null;
    if (!isPlaying || liveBpmSerumBusy) return;
    const bpm = getBpm();
    liveBpmSerumBusy = true;
    setStatus(`Re-bouncing Serum @ ${bpm} BPM…`);
    (async () => {
      try {
        for (const role of roles) {
          if (!isPlaying) break;
          if (
            serumStemMeta[role] &&
            !serumStemMeta[role].stale &&
            Math.abs(serumStemMeta[role].bpm - getBpm()) <= 0.25
          ) {
            continue;
          }
          // JS synth already covering at new BPM; swap to real stem when ready
          await refreshPlayingTrack(role, {
            provisionalJs: true,
            keepOldUntilReady: false,
          });
        }
      } catch (e) {
        console.warn("BPM Serum refresh failed:", e);
      } finally {
        liveBpmSerumBusy = false;
        if (isPlaying) {
          setStatus(`Serum @ ${getBpm()} BPM · ${playingStatusLine()}`);
        }
      }
    })();
  }, 200);
}

function onBpmInput() {
  markWaveDirty();
  if (!isPlaying) {
    drawWaveformFrame();
    return;
  }
  // Sample loops tagged with native BPM: warp rate only (filename-based).
  retuneWarpedSources();
  // Kicks follow BPM immediately (step timing). Serum is a fixed bounce —
  // stop old-tempo audio now and re-render at the new BPM (pitch-correct).
  invalidateSerumStemsForBpmChange();
  scheduleSerumRefreshForNewBpm();
  setStatus(`Tempo ${getBpm()} BPM · re-bouncing Serum…`);
}

function ensureSlotEl(role) {
  return $(`.slot[data-role="${role}"]`);
}

function syncMuteUi(role) {
  const slot = ensureSlotEl(role);
  if (!slot) return;
  const muted = Boolean(state.slots[role]?.muted);
  slot.classList.toggle("muted", muted);
  const muteBtn = $(".icon-btn.mute", slot);
  if (muteBtn) {
    muteBtn.classList.toggle("on", muted);
    muteBtn.setAttribute("aria-pressed", String(muted));
    muteBtn.textContent = muted ? "🔇" : "🔊";
    muteBtn.dataset.tip = muted
      ? "Unmute this track (live while playing)"
      : "Mute this track (live while playing)";
  }
  if (muted) slot.classList.remove("active");
  syncSoloUi(role);
}

function syncSoloUi(role) {
  const slot = ensureSlotEl(role);
  if (!slot) return;
  const solo = Boolean(state.slots[role]?.solo);
  const soloing = anySoloActive();
  slot.classList.toggle("soloed", solo);
  slot.classList.toggle("solo-dim", soloing && !solo);
  const soloBtn = $(".icon-btn.solo", slot);
  if (soloBtn) {
    soloBtn.classList.toggle("on", solo);
    soloBtn.setAttribute("aria-pressed", String(solo));
    soloBtn.dataset.tip = solo
      ? "Unsolo this track"
      : "Solo this track (silence others)";
  }
}

function toggleMute(role) {
  pushUndo(state.slots[role]?.muted ? `Unmute · ${role}` : `Mute · ${role}`);
  const cur = state.slots[role] || {};
  const muted = !cur.muted;
  state.slots[role] = { ...cur, muted };
  syncMuteUi(role);
  applyTrackMute(role);
  markWaveDirty();
  if (!isPlaying) drawWaveformFrame();
  if (isPlaying) setStatus(playingStatusLine());
  else setStatus(muted ? `Muted ${role}` : `Unmuted ${role}`);
}

function toggleSolo(role) {
  pushUndo(state.slots[role]?.solo ? `Unsolo · ${role}` : `Solo · ${role}`);
  const cur = state.slots[role] || {};
  const solo = !cur.solo;
  state.slots[role] = { ...cur, solo };
  // Solo change re-evaluates every track's gain
  applyAllTrackGains();
  markWaveDirty();
  if (!isPlaying) drawWaveformFrame();
  if (isPlaying) setStatus(playingStatusLine());
  else setStatus(solo ? `Solo ${role}` : `Unsolo ${role}`);
}

function applySlot(role, data) {
  const slot = ensureSlotEl(role);
  if (!slot) return;

  // Drop cached buffer if path changed
  const prev = state.slots[role]?.path;
  const pathChanged = Boolean(prev && data.path && prev !== data.path);
  if (pathChanged) {
    bufferCache.delete(prev);
  }

  const muted = Boolean(state.slots[role]?.muted);
  const solo = Boolean(state.slots[role]?.solo);
  const keepType =
    state.slots[role]?.serumType ||
    (isSerumTrack(role) ? baseType(role) : "any");
  const keepMidi =
    data.midi !== undefined ? data.midi : state.slots[role]?.midi || null;
  // Macros are tied to a specific .fxp — clear on preset change
  let keepMacros = null;
  if (data.macros !== undefined) {
    keepMacros = copyMacros(data.macros);
  } else if (!pathChanged) {
    keepMacros = copyMacros(state.slots[role]?.macros);
  }
  const keepTrackType =
    state.slots[role]?.type || data.type || data.role || baseType(role);
  state.slots[role] = {
    ...data,
    type: keepTrackType,
    locked: Boolean(state.slots[role]?.locked || data.locked),
    muted,
    solo,
    midi: keepMidi,
    macros: keepMacros,
    serumType: data.serumType || keepType,
  };

  const locked = Boolean(state.slots[role].locked);
  const nameEl = $(".slot-name", slot);
  const metaEl = $(".slot-meta", slot);
  setSlotNameEl(nameEl, data.name || "—");
  if (metaEl) {
    const meta = data.meta || "";
    metaEl.textContent = truncateDisplayName(meta, DISPLAY_NAME_MAX);
    if (meta.length > DISPLAY_NAME_MAX) metaEl.title = meta;
    else metaEl.removeAttribute("title");
  }

  slot.classList.toggle("optional", Boolean(data.empty));
  slot.classList.toggle("locked", locked);
  slot.classList.toggle("serum", data.kind === "serum");
  slot.classList.toggle("has-midi", Boolean(state.slots[role]?.midi));
  syncMuteUi(role);

  syncLockUi(role);

  // Keep meta showing MIDI summary for serum roles
  if (isSerumTrack(role) && state.slots[role]?.midi && window.MidiEngine) {
    const key = $("#key")?.value || "F minor";
    const sum = MidiEngine.midiSummary(state.slots[role].midi, key);
    if (metaEl && data.kind === "serum") {
      const fullMeta = `${data.meta || "Serum"} · ${sum}`;
      metaEl.textContent = truncateDisplayName(fullMeta, DISPLAY_NAME_MAX);
      if (fullMeta.length > DISPLAY_NAME_MAX) metaEl.title = fullMeta;
      else metaEl.removeAttribute("title");
    }
  }

}

function lockedPayload() {
  const out = {};
  for (const [role, s] of Object.entries(state.slots)) {
    if (s?.locked && s.path) {
      out[role] = {
        path: s.path,
        name: s.name,
        kind: s.kind,
        pack: s.pack,
        meta: s.meta,
      };
    }
  }
  return out;
}

function renderLibrary(summary) {
  if (!summary) return;
  const set = (id, val) => {
    const el = $(id);
    if (el) el.textContent = val;
  };
  set("#stat-samples", summary.sample_count ?? "—");
  const s1 = summary.serum1_count;
  const s2 = summary.serum2_count;
  if (s1 != null || s2 != null) {
    set("#stat-serum", `${summary.serum_count ?? 0}`);
    const label = document.querySelector("#stat-serum")?.nextElementSibling;
    if (label && label.tagName === "SPAN") {
      label.textContent =
        s1 != null && s2 != null ? `Serum (${s1}+${s2})` : "Serum";
    }
  } else {
    set("#stat-serum", summary.serum_count ?? "—");
  }
  set("#stat-packs", summary.pack_count ?? "—");

  const ul = $("#role-counts");
  if (ul && summary.role_counts) {
    ul.innerHTML = "";
    for (const [role, n] of Object.entries(summary.role_counts)) {
      const li = document.createElement("li");
      li.innerHTML = `<span>${role}</span><b>${n}</b>`;
      ul.appendChild(li);
    }
  }

  const paths = $all(".library-panel .path.mono");
  const roots = [...(summary.sample_roots || []), ...(summary.serum_roots || [])];
  paths.forEach((el, i) => {
    if (roots[i]) el.textContent = roots[i];
  });

  if (summary.serum_categories) {
    populateSerumTypeSelects(summary.serum_categories);
  }
}

async function loadLibrary() {
  const summary = await api("/api/library");
  renderLibrary(summary);
  if (summary.last_error) {
    setStatus(`Library loaded with warnings: ${summary.last_error}`);
  } else {
    setStatus(
      `Library ready · ${summary.sample_count} samples · ${summary.serum_count} Serum` +
        (summary.serum2_count != null
          ? ` (${summary.serum1_count || 0} v1 + ${summary.serum2_count || 0} v2)`
          : " presets")
    );
  }
  return summary;
}

async function doScan() {
  setStatus("Scanning library…");
  bufferCache.clear();
  const summary = await api("/api/scan", { method: "POST", body: "{}" });
  renderLibrary(summary);
  setStatus(
    `Scan complete · ${summary.sample_count} samples · ${summary.serum_count} Serum` +
      (summary.serum2_count != null
        ? ` (${summary.serum1_count || 0} v1 + ${summary.serum2_count || 0} v2)`
        : "")
  );
  return summary;
}

function ensureSlotMidi(role) {
  if (!window.MidiEngine) return null;
  if (!isSerumTrack(role)) return null;
  const key = $("#key")?.value || "F minor";
  if (!state.slots[role]) state.slots[role] = {};
  const midiRole = baseType(role) === "bass" ? "bass" : "lead";
  if (!state.slots[role].midi) {
    state.slots[role].midi = MidiEngine.createMidiState(midiRole, key);
  } else {
    state.slots[role].midi.key = key;
  }
  return state.slots[role].midi;
}

function rekeyAllMidi() {
  if (!window.MidiEngine) return;
  const key = $("#key")?.value || "F minor";
  for (const role of activeTrackIds()) {
    if (state.slots[role]?.midi) {
      state.slots[role].midi.key = key;
      const s = state.slots[role];
      applySlot(role, { ...s, locked: s.locked });
      if (isPlaying && isSerumTrack(role)) {
        scheduleLiveSerumRefresh(role, { delayMs: 200 });
      }
    }
  }
}

const SERUM_ENGINE_LABEL = { s1: "Serum 1", s2: "Serum 2", both: "Serum 1+2", none: "none" };

/** Sync checkbox UI → state.options.serum1/2 */
function readSerumEngineOptionsFromDom() {
  const s1 = $("#opt-serum1");
  const s2 = $("#opt-serum2");
  if (s1) state.options.serum1 = Boolean(s1.checked);
  if (s2) state.options.serum2 = Boolean(s2.checked);
}

function syncSerumEngineOptionsUi() {
  const s1 = $("#opt-serum1");
  const s2 = $("#opt-serum2");
  if (s1) s1.checked = state.options.serum1 !== false;
  if (s2) s2.checked = state.options.serum2 !== false;
}

/**
 * Global Serum engine filter from Options checkboxes.
 * @returns {"s1"|"s2"|"both"|"none"}
 */
function getSerumEngine() {
  readSerumEngineOptionsFromDom();
  const s1 = state.options.serum1 !== false;
  const s2 = state.options.serum2 !== false;
  if (s1 && s2) return "both";
  if (s1) return "s1";
  if (s2) return "s2";
  return "none";
}

function serumEngineLabel(eng) {
  return SERUM_ENGINE_LABEL[eng] || eng || "Serum";
}

function serumEnginesPayload() {
  const eng = getSerumEngine();
  const out = {};
  for (const id of activeTrackIds()) {
    if (isSerumTrack(id)) out[id] = eng;
  }
  return out;
}

const DEFAULT_SERUM_TYPES = [
  "bass",
  "lead",
  "arp",
  "pad",
  "pluck",
  "seq",
  "synth",
  "keys",
  "piano",
  "organ",
  "hoover",
  "bell",
  "chord",
  "guitar",
  "mallet",
  "loop",
  "fx",
  "vocal",
  "any",
];

function getSerumType(role) {
  const v = (state.slots[role]?.serumType || "").toLowerCase();
  if (v) return v;
  return isSerumTrack(role) ? baseType(role) : "any";
}

function serumTypesPayload() {
  const out = {};
  for (const id of activeTrackIds()) {
    if (isSerumTrack(id)) out[id] = getSerumType(id);
  }
  return out;
}

function orderedSerumTypeOptions(categories) {
  const cats = Array.isArray(categories) && categories.length
    ? [...new Set([...categories, ...DEFAULT_SERUM_TYPES])]
    : DEFAULT_SERUM_TYPES;
  const preferred = DEFAULT_SERUM_TYPES.filter((c) => c !== "any");
  const rest = cats
    .map((c) => String(c).toLowerCase())
    .filter((c) => c && c !== "any" && !preferred.includes(c))
    .sort();
  return [...preferred, ...rest, "any"];
}

function populateSerumTypeSelects(categories) {
  const ordered = orderedSerumTypeOptions(categories);
  for (const role of activeTrackIds()) {
    if (!isSerumTrack(role)) continue;
    const sel = $(`.slot-role-select[data-role="${role}"]`);
    if (!sel) continue;
    const cur = getSerumType(role);
    sel.innerHTML = "";
    for (const c of ordered) {
      const opt = document.createElement("option");
      opt.value = c;
      opt.textContent = c === "any" ? "ANY" : c.toUpperCase();
      if (c === cur) opt.selected = true;
      sel.appendChild(opt);
    }
    if (![...sel.options].some((o) => o.value === cur)) {
      sel.value = baseType(role) || "bass";
    } else {
      sel.value = cur;
    }
  }
}

function tracksPayload() {
  const eng = getSerumEngine();
  return activeTrackIds().map((id) => {
    const s = state.slots[id] || {};
    return {
      id,
      type: baseType(id),
      locked: Boolean(s.locked),
      path: s.path || null,
      name: s.name || "",
      kind: s.kind || null,
      pack: s.pack || "",
      meta: s.meta || "",
      ext: s.ext || null,
      serum_engine: eng,
      serum_type: getSerumType(id),
    };
  });
}

function getFilterRisers() {
  const el = $("#opt-filter-risers");
  if (el) return Boolean(el.checked);
  return state.options?.filterRisers !== false;
}

function getFilterFactorySerum() {
  const el = $("#opt-filter-factory-serum");
  if (el) return Boolean(el.checked);
  return Boolean(state.options?.filterFactorySerum);
}

function syncFilterFactorySerumUi() {
  const el = $("#opt-filter-factory-serum");
  if (el) el.checked = Boolean(state.options.filterFactorySerum);
}

function setOptionsPanelOpen(open) {
  const panel = $("#options-panel");
  const btn = $("#btn-options");
  if (!panel) return;
  if (open) panel.removeAttribute("hidden");
  else panel.setAttribute("hidden", "");
  btn?.setAttribute("aria-expanded", String(open));
}

/** Collect current Options + session fields for persistence. */
function collectUserSettings() {
  readSerumEngineOptionsFromDom();
  const filterEl = $("#opt-filter-risers");
  if (filterEl) state.options.filterRisers = Boolean(filterEl.checked);
  const facEl = $("#opt-filter-factory-serum");
  if (facEl) state.options.filterFactorySerum = Boolean(facEl.checked);
  ensureInstrumentsState();
  readInstrumentsFromDom();
  return {
    bpm: getBpm(),
    key: $("#key")?.value || "F minor",
    style: ($("#style")?.value || "Techno").trim() || "Techno",
    filterRisers: Boolean(state.options.filterRisers),
    filterFactorySerum: Boolean(state.options.filterFactorySerum),
    serum1: state.options.serum1 !== false,
    serum2: state.options.serum2 !== false,
    instruments: { ...state.options.instruments },
  };
}

/** Apply settings object to state + DOM (no save). */
function applyUserSettings(s) {
  if (!s || typeof s !== "object") return;
  if (s.bpm != null) {
    const bpmEl = $("#bpm");
    const n = Number(s.bpm);
    if (bpmEl && Number.isFinite(n)) bpmEl.value = String(Math.min(200, Math.max(60, n)));
  }
  if (s.key != null && $("#key")) {
    const keyEl = $("#key");
    const val = String(s.key);
    if ([...keyEl.options].some((o) => o.value === val || o.textContent === val)) {
      keyEl.value = val;
    } else {
      // custom key not in list — pick closest or leave
      const opt = [...keyEl.options].find((o) => o.textContent === val);
      if (opt) keyEl.value = opt.value;
    }
  }
  if (s.style != null && $("#style")) {
    $("#style").value = String(s.style);
  }
  // Default ON when key omitted (first-run / older saves without the field)
  state.options.filterRisers =
    s.filterRisers === undefined || s.filterRisers === null
      ? true
      : Boolean(s.filterRisers);
  const filterEl = $("#opt-filter-risers");
  if (filterEl) filterEl.checked = state.options.filterRisers;
  state.options.serum1 = s.serum1 !== false && s.serum1 !== 0;
  state.options.serum2 = s.serum2 !== false && s.serum2 !== 0;
  state.options.filterFactorySerum = Boolean(s.filterFactorySerum);
  if (s.instruments && typeof s.instruments === "object") {
    state.options.instruments = { ...defaultInstrumentsMap(), ...s.instruments };
  } else {
    ensureInstrumentsState();
  }
  ensureInstrumentsState();
  syncSerumEngineOptionsUi();
  syncFilterFactorySerumUi();
  syncInstrumentCheckboxesUi();
}

let settingsSaveTimer = null;
let settingsSaveInFlight = false;

/** Debounced persist to backend (user_settings.json). */
function scheduleSaveUserSettings({ immediate = false } = {}) {
  if (isFileProtocol()) return;
  if (settingsSaveTimer) {
    clearTimeout(settingsSaveTimer);
    settingsSaveTimer = null;
  }
  const run = () => {
    settingsSaveTimer = null;
    persistUserSettings().catch((e) =>
      console.warn("settings save failed:", e.message || e)
    );
  };
  if (immediate) run();
  else settingsSaveTimer = setTimeout(run, 400);
}

async function persistUserSettings() {
  if (isFileProtocol() || settingsSaveInFlight) {
    if (settingsSaveInFlight) scheduleSaveUserSettings();
    return;
  }
  settingsSaveInFlight = true;
  try {
    const body = collectUserSettings();
    await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify(body),
    });
  } finally {
    settingsSaveInFlight = false;
  }
}

async function loadUserSettings() {
  const res = await api("/api/settings");
  const s = res.settings || res;
  applyUserSettings(s);
  return s;
}

async function doGenerate() {
  stopAll();
  const eng = getSerumEngine();
  if (eng === "none") {
    setStatus("Options · enable Serum 1 and/or Serum 2 for synth tracks");
  }
  const body = {
    bpm: Number($("#bpm")?.value || 140),
    key: $("#key")?.value || "F minor",
    style: $("#style")?.value || "Techno",
    tracks: tracksPayload(),
    filter_risers: getFilterRisers(),
    filter_factory_serum: getFilterFactorySerum(),
  };
  setStatus("Generating…");
  beginTransportBusy("Generating…");
  let loop;
  try {
    loop = await api("/api/generate", {
      method: "POST",
      body: JSON.stringify(body),
    });
  } finally {
    endTransportBusy();
  }
  pushUndo("Generate");
  for (const [role, slot] of Object.entries(loop.slots || {})) {
    if (!state.slots[role]) continue;
    const locked = Boolean(state.slots[role]?.locked);
    const prevMidi = state.slots[role]?.midi;
    const prevType = state.slots[role]?.serumType;
    const prevTrackType = state.slots[role]?.type;
    applySlot(role, { ...slot, locked, type: prevTrackType || slot.role });
    if (isSerumTrack(role)) {
      if (prevType) state.slots[role].serumType = prevType;
      if (prevTrackType) state.slots[role].type = prevTrackType;
      if (locked && prevMidi) state.slots[role].midi = prevMidi;
      else if (!state.slots[role].midi) ensureSlotMidi(role);
      else if (!locked) {
        state.slots[role].midi = prevMidi || ensureSlotMidi(role);
      }
      applySlot(role, { ...state.slots[role], locked });
    }
  }
  setStatus(
    `Generated · ${loop.bpm} BPM · ${loop.key} · ${loop.style} · ${serumEngineLabel(eng)} — press Play`
  );
}

async function doReroll(role) {
  if (state.slots[role]?.locked) {
    setStatus(`${role} is locked — unlock first`);
    return;
  }
  const t = baseType(role);
  const engFinal = getSerumEngine();
  const stype = getSerumType(role);
  if (isSerumTrack(role) && engFinal === "none") {
    setStatus("Options · enable Serum 1 and/or Serum 2 to dice synth tracks");
    return;
  }

  beginTransportBusy(`Dice · ${role}…`);
  let data;
  try {
    data = await api("/api/reroll", {
      method: "POST",
      body: JSON.stringify({
        slot: t,
        current_path: state.slots[role]?.path || null,
        serum_engine: engFinal === "none" ? "both" : engFinal,
        serum_type: stype,
        filter_risers: getFilterRisers(),
        filter_factory_serum: getFilterFactorySerum(),
      }),
    });
  } finally {
    endTransportBusy();
  }
  pushUndo(`Dice · ${role}`);
  const prevType = state.slots[role]?.serumType;
  const prevTrackType = state.slots[role]?.type;
  applySlot(role, { ...data, locked: false, macros: null, type: prevTrackType || t });
  if (prevType) state.slots[role].serumType = prevType;
  if (prevTrackType) state.slots[role].type = prevTrackType;
  if (midiEditors[role]) {
    midiEditors[role].draft.macros = null;
    midiEditors[role].draft.macrosTouched = false;
    loadMacrosForEditor(role);
  }
  if (data.empty) {
    setStatus(
      `No match · ${role} · ${serumEngineLabel(engFinal)}` +
        (engFinal === "s2" ? " (need Serum 2 in library — Rescan / restart server)" : "") +
        (engFinal === "s1" ? " (need Serum 1 .fxp in library)" : "")
    );
    if (isPlaying) {
      stopSourcesForRole(role);
      delete scheduler.buffers[role];
      delete serumStemRoles[role];
      scheduler.playable = scheduler.playable.filter((r) => r !== role);
    }
    return;
  }
  const ext = (data.ext || data.path || "").toString().toLowerCase();
  const kind =
    ext.includes("serumpreset") || ext.endsWith(".serumpreset")
      ? "S2"
      : ext.includes(".fxp")
        ? "S1"
        : "?";
  setStatus(`Rerolled ${role} · ${kind} · ${data.name || ""}`);
  // Live transport: re-bounce Serum / reload sample so dice is audible immediately
  if (isPlaying) {
    try {
      await refreshPlayingTrack(role);
      if (isPlaying && state.slots[role]?.path) {
        setStatus(`Rerolled ${role} · ${kind} · ${data.name || ""} · live`);
      }
    } catch (e) {
      setStatus(`Reroll live update failed: ${e.message || e}`);
    }
  }
}

/** M — toggle monophonic MIDI editor for this serum track (stacks with others). */
function doNewMidi(role) {
  openMidiEditor(role);
}

function midiQ(role, sel) {
  const root = midiEditors[role]?.root;
  return root ? $(sel, root) : null;
}

function syncMidiEditingClasses() {
  document.querySelectorAll(".slot.midi-editing").forEach((el) => {
    el.classList.remove("midi-editing");
  });
  for (const role of Object.keys(midiEditors)) {
    ensureSlotEl(role)?.classList.add("midi-editing");
  }
}

/** Launch full Serum plugin UI for a specific track's preset. */
async function openSerumUi(role) {
  if (!role || !midiEditors[role]) {
    setStatus("Open MIDI editor (M) first");
    return;
  }
  const path = state.slots[role]?.path;
  const body = {};
  if (path) {
    const pl = String(path).toLowerCase();
    if (pl.endsWith(".fxp") || pl.endsWith(".serumpreset")) body.fxp = path;
  }
  setStatus(`Opening Serum UI${body.fxp ? " · loading preset…" : "…"}`);
  const result = await api("/api/serum/open", {
    method: "POST",
    body: JSON.stringify(body),
  });
  const name = body.fxp ? String(body.fxp).split(/[/\\]/).pop() : "init";
  setStatus(`Serum UI launched (pid ${result.pid}) · ${name} — close the window when done`);
}

function buildMidiEditorElement(role) {
  const sec = document.createElement("section");
  sec.className = "midi-section";
  sec.dataset.track = role;
  sec.setAttribute("aria-label", `MIDI editor · ${role}`);
  sec.innerHTML = `
    <div class="midi-card">
      <header class="midi-header">
        <div>
          <h2 class="midi-title">MIDI · ${role}</h2>
          <p class="hint midi-subtitle">Single-note pattern · selected key</p>
        </div>
        <div class="midi-header-actions">
          <button type="button" class="btn serum-open" data-action="serum" data-tip="Open full Serum plugin UI for this track">
            <span class="serum-mark" aria-hidden="true">◈</span> Serum
          </button>
          <button type="button" class="btn ghost" data-action="close" data-tip="Hide this MIDI editor">Close</button>
        </div>
      </header>
      <div class="midi-toolbar">
        <label class="field">
          <span>Pattern</span>
          <select class="midi-pattern"></select>
        </label>
        <label class="field">
          <span>Length</span>
          <select class="midi-length" title="Default length for new notes"></select>
        </label>
        <label class="field">
          <span>Octave</span>
          <input type="number" class="midi-octave" min="0" max="7" value="3" />
        </label>
        <label class="field grow">
          <span>Key</span>
          <input type="text" class="midi-key-display" readonly />
        </label>
        <button type="button" class="btn ghost" data-action="next" data-tip="Next pattern in the dropdown list">Next pattern</button>
        <button type="button" class="btn ghost" data-action="clear" data-tip="Clear all steps">Clear</button>
      </div>
      <div class="midi-grid-wrap">
        <div class="midi-step-labels"></div>
        <div class="midi-grid" role="grid" aria-label="16th-note pattern"></div>
      </div>
      <p class="hint midi-help">
        Click empty to place · click note to remove · Shift+click cycles degree (1–7).
        Drag the right edge of a note (or Alt+drag) to change length · monophonic.
      </p>
      <div class="midi-preview-line mono midi-note-list"></div>
      <div class="midi-macros">
        <div class="midi-macros-head">
          <h3>Serum macros</h3>
          <p class="hint midi-macros-status">Load a Serum preset, then open M</p>
        </div>
        <div class="midi-macros-grid"></div>
      </div>
    </div>
  `;
  return sec;
}

function bindMidiEditorRoot(role, root) {
  const on = (action, fn) => {
    const el = $(`[data-action="${action}"]`, root);
    el?.addEventListener("click", fn);
  };
  on("close", () => closeMidiEditor(role));
  on("serum", () => {
    openSerumUi(role).catch((e) => setStatus(`Open Serum failed: ${e.message || e}`));
  });
  on("next", () => {
    const ed = midiEditors[role];
    const sel = $(".midi-pattern", root);
    if (!ed || !window.MidiEngine || !sel) return;
    const opts = [...sel.options].filter((o) => o.value && o.value !== "custom");
    if (!opts.length) return;
    const cur = ed.draft.patternId || sel.value;
    let idx = opts.findIndex((o) => o.value === cur);
    // From custom / unknown → start at first; else advance and wrap
    idx = idx < 0 ? 0 : (idx + 1) % opts.length;
    const id = opts[idx].value;
    ed.draft.patternId = id;
    ed.draft.grid = MidiEngine.buildPatternGrid(id);
    sel.value = id;
    renderMidiEditor(role);
    commitMidiDraft(role);
    setStatus(`Pattern · ${role} · ${opts[idx].textContent || id}`);
  });
  on("clear", () => {
    const ed = midiEditors[role];
    if (!ed) return;
    ed.draft.grid = Array.from({ length: 16 }, () => null);
    ed.draft.patternId = "custom";
    renderMidiEditor(role);
    commitMidiDraft(role);
  });
  const sel = $(".midi-pattern", root);
  sel?.addEventListener("change", () => {
    const ed = midiEditors[role];
    if (!ed || !window.MidiEngine) return;
    const id = sel.value;
    if (id === "custom") return;
    ed.draft.patternId = id;
    ed.draft.grid = MidiEngine.buildPatternGrid(id);
    renderMidiEditor(role);
    commitMidiDraft(role);
  });
  const lenSel = $(".midi-length", root);
  lenSel?.addEventListener("change", () => {
    const ed = midiEditors[role];
    if (!ed) return;
    ed.draft.noteLength = Math.max(1, Math.min(16, Number(lenSel.value) || 2));
  });
  const oct = $(".midi-octave", root);
  oct?.addEventListener("change", () => {
    const ed = midiEditors[role];
    if (!ed) return;
    ed.draft.octave = Number(oct.value);
    renderMidiEditor(role);
    commitMidiDraft(role);
  });
  oct?.addEventListener("input", () => {
    const ed = midiEditors[role];
    if (!ed) return;
    ed.draft.octave = Number(oct.value);
    renderMidiEditor(role);
    commitMidiDraft(role, { silent: true });
  });
}

function closeMidiEditor(role) {
  const ed = midiEditors[role];
  if (!ed) return;
  ed.root?.remove();
  delete midiEditors[role];
  syncMidiEditingClasses();
  setStatus(`MIDI editor closed · ${role}`);
}

function openMidiEditor(role) {
  if (!window.MidiEngine) {
    setStatus("MIDI engine failed to load (midi.js)");
    return;
  }
  if (!isSerumTrack(role)) {
    setStatus("MIDI editor is for Serum tracks");
    return;
  }
  // Toggle only this track — leave others open
  if (midiEditors[role]) {
    closeMidiEditor(role);
    return;
  }
  const key = $("#key")?.value || "F minor";
  const existing = state.slots[role]?.midi;
  const midiRole = baseType(role) === "bass" ? "bass" : "lead";
  const draft = existing
    ? {
        patternId: existing.patternId,
        octave: existing.octave,
        key,
        grid: existing.grid.map((c) => (c ? { ...c } : null)),
        noteLength: 2,
        macros: copyMacros(state.slots[role]?.macros),
        macrosTouched: Array.isArray(state.slots[role]?.macros),
        macroMeta: null,
      }
    : {
        ...MidiEngine.createMidiState(midiRole, key),
        noteLength: 2,
        macros: copyMacros(state.slots[role]?.macros),
        macrosTouched: Array.isArray(state.slots[role]?.macros),
        macroMeta: null,
      };

  const root = buildMidiEditorElement(role);
  const host = $("#midi-editors");
  host?.appendChild(root);
  midiEditors[role] = { role, draft, root };
  bindMidiEditorRoot(role, root);
  renderMidiEditor(role);
  syncMidiEditingClasses();
  root.scrollIntoView({ behavior: "smooth", block: "nearest" });
  setStatus(`MIDI editor · ${role} · ${Object.keys(midiEditors).length} open`);
  loadMacrosForEditor(role);
}

function copyMacros(src) {
  if (!Array.isArray(src) || !src.length) return null;
  return src.slice(0, 8).map((v) => max01(v));
}

function max01(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(1, n));
}

async function loadMacrosForEditor(role) {
  const ed = midiEditors[role];
  if (!ed) return;
  const wrap = $(".midi-macros", ed.root);
  const status = $(".midi-macros-status", ed.root);
  wrap?.classList.add("is-loading");
  wrap?.classList.remove("is-empty", "is-hidden");
  if (status) status.textContent = "Loading macros from preset…";

  const path = state.slots[role]?.path;
  const pl = path ? String(path).toLowerCase() : "";
  if (!pl.endsWith(".fxp") && !pl.endsWith(".serumpreset")) {
    ed.draft.macroMeta = [];
    ed.draft.macros = null;
    wrap?.classList.remove("is-loading");
    wrap?.classList.add("is-empty");
    if (status) status.textContent = "No Serum preset on this slot — Generate/dice first";
    renderMacroSliders(role);
    return;
  }

  try {
    const result = await api("/api/serum/macros", {
      method: "POST",
      body: JSON.stringify({ fxp: path }),
    });
    if (!midiEditors[role]) return;
    applyMacroResult(role, result);
  } catch (e) {
    if (!midiEditors[role]) return;
    // Host may crash after success; error text can still embed ok:true JSON
    const recovered = tryParseMacrosFromError(e);
    if (recovered) {
      applyMacroResult(role, recovered);
      return;
    }
    ed.draft.macroMeta = [];
    if (!ed.draft.macros) ed.draft.macros = null;
    wrap?.classList.remove("is-loading");
    wrap?.classList.add("is-empty");
    const msg = String(e.message || e);
    if (status) {
      status.textContent =
        /not found/i.test(msg)
          ? "Macros API missing — restart the backend (uvicorn), then reopen M"
          : `Macros unavailable: ${msg.length > 120 ? msg.slice(0, 120) + "…" : msg}`;
    }
    renderMacroSliders(role);
  }
}

/** If error detail embeds a successful macros JSON blob, parse it. */
function tryParseMacrosFromError(err) {
  const msg = String(err?.message || err || "");
  const brace = msg.indexOf("{");
  if (brace < 0) return null;
  try {
    const obj = JSON.parse(msg.slice(brace));
    if (obj && obj.ok && (Array.isArray(obj.macros) || Array.isArray(obj.all_macros))) {
      return obj;
    }
  } catch {
    /* ignore */
  }
  return null;
}

function applyMacroResult(role, result) {
  const ed = midiEditors[role];
  if (!ed) return;
  const wrap = $(".midi-macros", ed.root);
  const status = $(".midi-macros-status", ed.root);
  const mapped = Array.isArray(result.macros) ? result.macros : [];
  const all = Array.isArray(result.all_macros) ? result.all_macros : mapped;
  const nSlots = Math.max(4, all.length, mapped.length, 8);
  const baseline = Array.from({ length: nSlots }, () => 0);
  for (const m of all) {
    const slot = Number(m.slot) || 0;
    if (slot >= 1 && slot <= nSlots) baseline[slot - 1] = max01(m.value ?? 0);
  }
  ed.draft.macroMeta = mapped.map((m) => ({
    slot: Number(m.slot) || 1,
    name: m.name || `Macro ${m.slot}`,
    value: max01(m.value ?? 0),
    index: m.index,
    mapped: true,
  }));
  if (!ed.draft.macrosTouched || !ed.draft.macros) {
    ed.draft.macros = baseline;
    ed.draft.macrosTouched = false;
  } else {
    for (let i = 0; i < nSlots; i++) {
      if (ed.draft.macros[i] == null) ed.draft.macros[i] = baseline[i];
    }
  }
  wrap?.classList.remove("is-loading");
  if (!mapped.length) {
    wrap?.classList.add("is-empty");
    if (status) status.textContent = "No macros mapped on this preset";
  } else {
    wrap?.classList.remove("is-empty");
    if (status) {
      const loaded = result.fxp_loaded ? "preset loaded" : "preset load uncertain";
      status.textContent = ed.draft.macrosTouched
        ? `${mapped.length} macro${mapped.length === 1 ? "" : "s"} · custom · ${loaded}`
        : `${mapped.length} macro${mapped.length === 1 ? "" : "s"} · ${loaded}`;
    }
  }
  renderMacroSliders(role);
}

function renderMacroSliders(role) {
  const ed = midiEditors[role];
  if (!ed) return;
  const grid = $(".midi-macros-grid", ed.root);
  const wrap = $(".midi-macros", ed.root);
  if (!grid) return;
  const meta = Array.isArray(ed.draft.macroMeta) ? ed.draft.macroMeta : [];
  const vals = ed.draft.macros || [0, 0, 0, 0];
  grid.innerHTML = "";
  grid.style.setProperty("--macro-cols", String(Math.max(1, meta.length)));

  if (!meta.length) {
    wrap?.classList.add("is-empty");
    return;
  }
  wrap?.classList.remove("is-empty");

  meta.forEach((m) => {
    const slotIdx = Math.max(0, (Number(m.slot) || 1) - 1);
    const val = max01(vals[slotIdx] ?? m.value ?? 0);
    const row = document.createElement("label");
    row.className = "midi-macro";
    const safeName = String(m.name || `Macro ${slotIdx + 1}`).replace(/[<>&"]/g, "");
    row.innerHTML = `
      <div class="midi-macro-label">
        <strong title="${safeName}">${safeName}</strong>
        <span class="midi-macro-val">${Math.round(val * 100)}</span>
      </div>
    `;
    const input = document.createElement("input");
    input.type = "range";
    input.min = "0";
    input.max = "100";
    input.step = "1";
    input.value = String(Math.round(val * 100));
    input.dataset.macroSlot = String(slotIdx);
    input.setAttribute("aria-label", safeName);
    input.addEventListener("input", () => {
      if (!midiEditors[role]) return;
      if (!ed.draft.macros) ed.draft.macros = [0, 0, 0, 0];
      const v = max01(Number(input.value) / 100);
      ed.draft.macros[slotIdx] = v;
      ed.draft.macrosTouched = true;
      const span = row.querySelector(".midi-macro-val");
      if (span) span.textContent = String(Math.round(v * 100));
      const st = $(".midi-macros-status", ed.root);
      if (st) st.textContent = isPlaying
        ? "Macros · updating live…"
        : "Macros live · used on next Play";
      commitMidiDraft(role, { silent: true });
    });
    row.appendChild(input);
    grid.appendChild(row);
  });
}

function markMidiCustom(role) {
  const ed = midiEditors[role];
  if (!ed) return;
  ed.draft.patternId = "custom";
  const sel = midiQ(role, ".midi-pattern");
  if (sel && ![...sel.options].some((o) => o.value === "custom")) {
    const opt = document.createElement("option");
    opt.value = "custom";
    opt.textContent = "Custom";
    sel.appendChild(opt);
  }
  if (sel) sel.value = "custom";
}

function lengthLabel(len) {
  const n = Number(len) || 1;
  const known = window.MidiEngine?.NOTE_LENGTHS?.find((x) => x.value === n);
  return known ? known.label : `${n}/16`;
}

function renderMidiEditor(role) {
  const ed = midiEditors[role];
  if (!ed || !window.MidiEngine) return;
  const { draft, root } = ed;
  const key = $("#key")?.value || "F minor";
  draft.key = key;
  if (draft.noteLength == null) draft.noteLength = 2;
  const midiRole = baseType(role) === "bass" ? "bass" : "lead";

  const title = $(".midi-title", root);
  const sub = $(".midi-subtitle", root);
  if (title) title.textContent = `MIDI · ${role}`;
  if (sub) sub.textContent = `Single-note · ${key} · type ${baseType(role)}`;

  const keyDisp = $(".midi-key-display", root);
  if (keyDisp) keyDisp.value = key;

  const oct = $(".midi-octave", root);
  if (oct) oct.value = String(draft.octave ?? MidiEngine.defaultOctave(midiRole));

  const sel = $(".midi-pattern", root);
  if (sel && !sel.dataset.ready) {
    sel.innerHTML = "";
    for (const p of MidiEngine.listPatterns()) {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.name;
      sel.appendChild(opt);
    }
    sel.dataset.ready = "1";
  }
  if (sel) sel.value = draft.patternId || MidiEngine.defaultPatternId(midiRole);

  const lenSel = $(".midi-length", root);
  if (lenSel && !lenSel.dataset.ready) {
    lenSel.innerHTML = "";
    for (const L of MidiEngine.NOTE_LENGTHS) {
      const opt = document.createElement("option");
      opt.value = String(L.value);
      opt.textContent = L.label;
      lenSel.appendChild(opt);
    }
    lenSel.dataset.ready = "1";
  }
  if (lenSel) lenSel.value = String(draft.noteLength || 2);

  const labels = $(".midi-step-labels", root);
  if (labels) {
    labels.innerHTML = "";
    for (let i = 0; i < 16; i++) {
      const s = document.createElement("span");
      s.textContent = String(i + 1);
      if (i % 4 === 0) s.style.color = "var(--text-dim)";
      labels.appendChild(s);
    }
  }

  const gridEl = $(".midi-grid", root);
  if (gridEl) {
    gridEl.innerHTML = "";
    const owner = Array(16).fill(null);
    for (let s = 0; s < 16; s++) {
      const cell = draft.grid[s];
      if (!cell) continue;
      const len = MidiEngine.clampLength(s, cell.length || 1, 16);
      for (let i = 0; i < len && s + i < 16; i++) owner[s + i] = s;
    }
    for (let i = 0; i < 16; i++) {
      const start = owner[i];
      const isStart = start === i;
      const isSustain = start != null && !isStart;
      const cell = isStart ? draft.grid[i] : null;
      const note = start != null ? draft.grid[start] : null;
      const noteLen = note ? MidiEngine.clampLength(start, note.length || 1, 16) : 0;
      const isEnd = start != null && i === start + noteLen - 1;

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className =
        "midi-cell" +
        (isStart ? " on" : "") +
        (isSustain ? " sustain" : "") +
        (isEnd ? " note-end" : "") +
        (i % 4 === 0 ? " beat" : "");
      btn.dataset.step = String(i);
      if (start != null) btn.dataset.noteStart = String(start);

      if (isStart && note) {
        const midi = MidiEngine.degreeToMidi(key, note.degree, draft.octave);
        btn.textContent = MidiEngine.midiToName(midi);
        btn.title = `deg ${note.degree + 1} · ${MidiEngine.midiToName(midi)} · ${lengthLabel(noteLen)} — drag right edge to resize`;
      } else if (isSustain && note) {
        btn.textContent = "—";
        btn.title = `Sustain · ${lengthLabel(noteLen)} — drag right edge to resize`;
      } else {
        btn.textContent = "·";
        btn.title = `Empty · click places ${lengthLabel(draft.noteLength || 2)}`;
      }

      btn.addEventListener("pointerdown", (ev) => {
        onMidiCellPointerDown(role, i, ev);
      });
      btn.addEventListener("pointermove", (ev) => {
        updateMidiResizeCursor(btn, role, i, ev);
      });
      btn.addEventListener("pointerleave", () => {
        btn.classList.remove("resize-edge");
      });
      gridEl.appendChild(btn);
    }
  }

  const notes = MidiEngine.gridToNotes(draft.grid, key, draft.octave, 1);
  const list = $(".midi-note-list", root);
  if (list) {
    if (!notes.length) list.textContent = "(empty bar)";
    else {
      list.textContent = notes
        .map((n) => `${n.step + 1}:${MidiEngine.midiToName(n.midi)}×${n.duration}`)
        .join("  ");
    }
  }
}

/** True when pointer is on the right ~40% of a note's last cell (resize handle). */
function isMidiResizeEdge(btn, step, noteStart, noteLen, ev) {
  const end = noteStart + noteLen - 1;
  if (step !== end) return false;
  const rect = btn.getBoundingClientRect();
  if (rect.width <= 0) return false;
  return (ev.clientX - rect.left) / rect.width >= 0.55;
}

function updateMidiResizeCursor(btn, role, step, ev) {
  const ed = midiEditors[role];
  if (!ed || !window.MidiEngine || ed._resizing) return;
  const hit = MidiEngine.findNoteAt(ed.draft.grid, step);
  if (!hit) {
    btn.classList.remove("resize-edge");
    return;
  }
  if (isMidiResizeEdge(btn, step, hit.start, hit.length, ev) || ev.altKey) {
    btn.classList.add("resize-edge");
  } else {
    btn.classList.remove("resize-edge");
  }
}

function stepFromClientX(gridEl, clientX) {
  const cells = [...gridEl.querySelectorAll(".midi-cell")];
  if (!cells.length) return 0;
  for (let i = 0; i < cells.length; i++) {
    const r = cells[i].getBoundingClientRect();
    if (clientX >= r.left && clientX < r.right) return i;
  }
  const first = cells[0].getBoundingClientRect();
  const last = cells[cells.length - 1].getBoundingClientRect();
  if (clientX < first.left) return 0;
  if (clientX >= last.right) return cells.length - 1;
  // Between gaps: nearest center
  let best = 0;
  let bestDist = Infinity;
  cells.forEach((c, i) => {
    const r = c.getBoundingClientRect();
    const mid = (r.left + r.right) / 2;
    const d = Math.abs(clientX - mid);
    if (d < bestDist) {
      bestDist = d;
      best = i;
    }
  });
  return best;
}

function onMidiCellPointerDown(role, step, ev) {
  if (ev.button != null && ev.button !== 0) return;
  const ed = midiEditors[role];
  if (!ed || !window.MidiEngine) return;
  const grid = ed.draft.grid;
  const hit = MidiEngine.findNoteAt(grid, step);
  const btn = ev.currentTarget;

  // Shift+click on note: cycle scale degree
  if (ev.shiftKey && hit) {
    ev.preventDefault();
    const cell = grid[hit.start];
    cell.degree = (cell.degree + 1) % 7;
    markMidiCustom(role);
    renderMidiEditor(role);
    commitMidiDraft(role);
    return;
  }

  // Resize: right edge of note end, or Alt+drag on any part of the note
  if (hit) {
    const wantResize =
      ev.altKey || isMidiResizeEdge(btn, step, hit.start, hit.length, ev);
    if (wantResize) {
      ev.preventDefault();
      startMidiResize(role, hit.start, ev);
      return;
    }
    // Click body/start removes the whole note
    ev.preventDefault();
    grid[hit.start] = null;
    markMidiCustom(role);
    renderMidiEditor(role);
    commitMidiDraft(role);
    return;
  }

  // Empty cell: place with toolbar length
  ev.preventDefault();
  const len = Math.max(1, Math.min(16, Number(ed.draft.noteLength) || 2));
  MidiEngine.place(grid, step, 0, len, 100);
  markMidiCustom(role);
  renderMidiEditor(role);
  commitMidiDraft(role);
}

function startMidiResize(role, noteStart, ev) {
  const ed = midiEditors[role];
  if (!ed || !window.MidiEngine) return;
  const gridEl = $(".midi-grid", ed.root);
  if (!gridEl) return;

  ed._resizing = true;
  ed.root?.classList.add("midi-resizing");
  const pointerId = ev.pointerId;
  try {
    ev.currentTarget?.setPointerCapture?.(pointerId);
  } catch {
    /* ignore */
  }

  const applyAt = (clientX) => {
    if (!midiEditors[role]) return;
    const grid = ed.draft.grid;
    if (!grid[noteStart]) return;
    const endStep = stepFromClientX(gridEl, clientX);
    const newLen = Math.max(1, endStep - noteStart + 1);
    const cur = grid[noteStart].length || 1;
    if (cur === newLen) return;
    MidiEngine.setNoteLength(grid, noteStart, newLen);
    markMidiCustom(role);
    // Keep resize flag through re-render (DOM rebuild)
    ed._resizing = true;
    renderMidiEditor(role);
  };

  applyAt(ev.clientX);

  const onMove = (e) => {
    applyAt(e.clientX);
  };
  const onUp = (e) => {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    window.removeEventListener("pointercancel", onUp);
    applyAt(e.clientX);
    ed._resizing = false;
    ed.root?.classList.remove("midi-resizing");
    commitMidiDraft(role);
    const len = ed.draft.grid[noteStart]?.length;
    if (len) setStatus(`MIDI · ${role} · length ${lengthLabel(len)}`);
  };
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
  window.addEventListener("pointercancel", onUp);
}

/** Write draft MIDI (+ macros if touched) to the slot immediately. */
function commitMidiDraft(role, opts = {}) {
  const ed = midiEditors[role];
  if (!ed || !window.MidiEngine) return;
  const { draft } = ed;
  const key = $("#key")?.value || "F minor";
  draft.key = key;
  const octEl = midiQ(role, ".midi-octave");
  draft.octave = Number(octEl?.value ?? draft.octave);
  // Snapshot before write (coalesced for rapid edits)
  pushMidiUndo(role);
  if (!state.slots[role]) state.slots[role] = {};
  state.slots[role].midi = {
    patternId: draft.patternId,
    octave: draft.octave,
    key,
    grid: draft.grid.map((c) => (c ? { ...c } : null)),
  };
  if (draft.macrosTouched && Array.isArray(draft.macros)) {
    state.slots[role].macros = draft.macros.slice(0, 8).map(max01);
  }
  applySlot(role, { ...state.slots[role], locked: state.slots[role].locked });
  ensureSlotEl(role)?.classList.add("midi-editing");
  markWaveDirty();
  if (!opts.silent) {
    setStatus(`MIDI · ${role} · ${MidiEngine.midiSummary(state.slots[role].midi, key)}`);
    if (!isPlaying) drawWaveformFrame();
  }
  // Serum: instant JS synth + background warm-host bounce
  if (isPlaying && isSerumTrack(role)) {
    scheduleLiveSerumRefresh(role, {
      delayMs: opts.silent ? 150 : 80,
    });
    if (!opts.silent) {
      setStatus(
        `MIDI · ${role} · ${MidiEngine.midiSummary(state.slots[role].midi, key)} · preview`
      );
    }
  }
}

function initMidiEditorUi() {
  $("#key")?.addEventListener("change", () => {
    rekeyAllMidi();
    for (const role of Object.keys(midiEditors)) {
      renderMidiEditor(role);
    }
  });
}

function syncLockUi(role) {
  const slot = ensureSlotEl(role);
  if (!slot) return;
  const locked = Boolean(state.slots[role]?.locked);
  const lockBtn = $(".icon-btn.lock", slot);
  slot.classList.toggle("locked", locked);
  if (!lockBtn) return;
  lockBtn.classList.toggle("on", locked);
  lockBtn.setAttribute("aria-pressed", String(locked));
  lockBtn.textContent = locked ? "🔒" : "🔓";
  lockBtn.setAttribute("aria-label", locked ? "Unlock" : "Lock");
  lockBtn.dataset.tip = locked
    ? "Unlock — allow Generate to change this track"
    : "Lock — keep this sound on Generate";
}

function toggleLock(role, _btn) {
  const cur =
    state.slots[role] || {
      name: $(`.slot[data-role="${role}"] .slot-name`)?.textContent,
    };
  pushUndo(cur.locked ? `Unlock · ${role}` : `Lock · ${role}`);
  const locked = !cur.locked;
  state.slots[role] = { ...cur, locked };
  syncLockUi(role);
  setStatus(locked ? `Locked ${role}` : `Unlocked ${role}`);
}

function serumTypeOptionsHtml(selected) {
  const ordered = orderedSerumTypeOptions([]);
  return ordered
    .map((c) => {
      const label = c === "any" ? "ANY" : c.toUpperCase();
      const sel = c === selected ? " selected" : "";
      return `<option value="${c}"${sel}>${label}</option>`;
    })
    .join("");
}

function buildSlotElement(id, type) {
  const serum = isSerumType(type);
  const art = document.createElement("article");
  art.className = "slot" + (serum ? " serum" : "") + (type === "fx" ? " optional" : "");
  art.dataset.role = id;
  art.dataset.type = type;

  const sampleLabel = {
    kick: "KICK",
    clap: "CLAP",
    hats: "HATS",
    perc: "PERC",
    fx: "FX",
    vocal: "VOCAL",
    lead_audio: "LEAD",
    loop: "LOOP",
    snare: "SNARE",
  };
  const roleHtml = serum
    ? `<label class="slot-role-wrap" data-tip="Serum type filter for Generate / dice">
        <select class="slot-role-select" data-role="${id}" aria-label="Serum type">
          ${serumTypeOptionsHtml(type)}
        </select>
      </label>`
    : `<div class="slot-role">${sampleLabel[type] || type.toUpperCase()}</div>`;

  const toolsHtml = serum
    ? `<div class="slot-serum-tools">
        <button type="button" class="icon-btn serum-m" data-tip="Edit MIDI pattern" aria-label="MIDI editor">M</button>
      </div>`
    : "";

  art.innerHTML = `
    ${roleHtml}
    <div class="slot-body">
      <div class="slot-name">${serum ? `Serum · ${type}` : "— empty —"}</div>
      <div class="slot-meta">${serum ? "preset · MIDI will follow key" : "optional · pick with Generate"}</div>
    </div>
    ${toolsHtml}
    <div class="slot-actions">
      <button type="button" class="icon-btn mute" data-tip="Mute / unmute" aria-pressed="false" aria-label="Mute">🔊</button>
      <button type="button" class="icon-btn solo" data-tip="Solo this track" aria-pressed="false" aria-label="Solo">S</button>
      <button type="button" class="icon-btn lock" data-tip="Lock — keep on Generate" aria-pressed="false" aria-label="Lock">🔓</button>
      <button type="button" class="icon-btn dice" data-tip="Reroll this track" aria-label="Reroll">🎲</button>
      <button type="button" class="icon-btn delete" data-tip="Remove track from stack" aria-label="Delete track">🗑️</button>
    </div>
  `;
  return art;
}

function bindSlotElement(art) {
  const role = art.dataset.role;
  const type = art.dataset.type || baseType(role);
  const lock = $(".icon-btn.lock", art);
  const dice = $(".icon-btn.dice", art);
  const mute = $(".icon-btn.mute", art);
  const solo = $(".icon-btn.solo", art);
  const del = $(".icon-btn.delete", art);
  const serumM = $(".icon-btn.serum-m", art);
  const typeSel = $(".slot-role-select", art);

  lock?.addEventListener("click", () => toggleLock(role, lock));
  mute?.addEventListener("click", () => toggleMute(role));
  solo?.addEventListener("click", () => toggleSolo(role));
  dice?.addEventListener("click", () => {
    doReroll(role).catch((e) => setStatus(`Reroll failed: ${e.message}`));
  });
  del?.addEventListener("click", () => removeTrack(role));
  serumM?.addEventListener("click", () => doNewMidi(role));
  typeSel?.addEventListener("change", () => {
    if (!state.slots[role]) state.slots[role] = {};
    pushUndo(`Type · ${role}`);
    const v = typeSel.value || type;
    state.slots[role].serumType = v;
    // Changing type filter also becomes the catalog type for dice
    state.slots[role].type = v === "any" ? type : v;
    art.dataset.type = state.slots[role].type;
    setStatus(`${role} · type ${String(v).toUpperCase()}`);
  });

  if (!state.slots[role]) {
    state.slots[role] = {
      type,
      name: $(".slot-name", art)?.textContent || "",
      meta: $(".slot-meta", art)?.textContent || "",
      path: null,
      locked: false,
      muted: false,
      solo: false,
      empty: type === "fx",
      midi: null,
      serumType: isSerumType(type) ? type : "any",
    };
  } else {
    state.slots[role].type = state.slots[role].type || type;
  }

  if (isSerumTrack(role)) {
    ensureSlotMidi(role);
  }
  syncLockUi(role);
  syncMuteUi(role);
  syncSoloUi(role);
}

function addTrack(type, { silent = false } = {}) {
  if (!silent) pushUndo("Add track");
  const t = (type || "bass").toLowerCase();
  const id = newTrackId(t);
  state.trackOrder.push(id);
  state.slots[id] = {
    type: t,
    name: isSerumType(t)
      ? `Serum · ${t}`
      : t === "lead_audio"
        ? "Lead sample"
        : "— empty —",
    meta: isSerumType(t)
      ? "preset · MIDI will follow key"
      : "pick with Generate / dice",
    path: null,
    locked: false,
    muted: false,
    solo: false,
    empty: true,
    midi: null,
    serumType: isSerumType(t) ? t : "any",
  };
  const list = $("#slot-list");
  const art = buildSlotElement(id, t);
  list?.appendChild(art);
  bindSlotElement(art);
  if (isSerumTrack(id)) ensureSlotMidi(id);
  if (!silent) {
    setStatus(`Added ${t} track`);
    doReroll(id).catch(() => {});
  }
  return id;
}

function removeTrack(id) {
  if (activeTrackIds().length <= 1) {
    setStatus("Keep at least one track");
    return;
  }
  pushUndo("Delete track");
  if (midiEditors[id]) closeMidiEditor(id);
  if (previewLoopRole === id) stopAll();
  state.trackOrder = state.trackOrder.filter((x) => x !== id);
  delete state.slots[id];
  $(`.slot[data-role="${id}"]`)?.remove();
  setStatus(`Removed track · Ctrl+Z to undo`);
}

function initDefaultTracks() {
  const list = $("#slot-list");
  if (!list) return;
  stopAll();
  closeAllMidiEditors();
  list.innerHTML = "";
  state.trackOrder = [];
  state.slots = {};
  trackSeq = 0;
  ensureInstrumentsState();
  const types = getDefaultTrackTypes();
  for (const t of types) {
    addTrack(t, { silent: true });
  }
}

function renderInstrumentCheckboxes() {
  const host = $("#opt-instruments");
  if (!host) return;
  ensureInstrumentsState();
  host.innerHTML = "";
  for (const d of INSTRUMENT_DEFS) {
    const lab = document.createElement("label");
    lab.className = "options-row";
    lab.dataset.tip = d.tip || d.label;
    lab.innerHTML = `
      <input type="checkbox" data-instrument="${d.id}" ${
        isInstrumentEnabled(d.id) ? "checked" : ""
      } />
      <span class="options-label"><strong></strong></span>
    `;
    $(".options-label strong", lab).textContent = d.label;
    const cb = $("input", lab);
    cb?.addEventListener("change", () => {
      ensureInstrumentsState();
      state.options.instruments[d.id] = Boolean(cb.checked);
      const n = enabledDefaultTrackTypes().length;
      setStatus(
        `Options · ${d.label} ${cb.checked ? "ON" : "OFF"} · ${n} default track${
          n === 1 ? "" : "s"
        }`
      );
      scheduleSaveUserSettings({ immediate: true });
      // Rebuild stack when idle so defaults are immediately usable
      if (!isPlaying && !isPlayPending) {
        initDefaultTracks();
        doGenerate().catch((e) => setStatus(`Generate failed: ${e.message}`));
      }
    });
    host.appendChild(lab);
  }
}

function syncInstrumentCheckboxesUi() {
  ensureInstrumentsState();
  for (const d of INSTRUMENT_DEFS) {
    const cb = $(`#opt-instruments input[data-instrument="${d.id}"]`);
    if (cb) cb.checked = isInstrumentEnabled(d.id);
  }
}

function readInstrumentsFromDom() {
  ensureInstrumentsState();
  for (const d of INSTRUMENT_DEFS) {
    const cb = $(`#opt-instruments input[data-instrument="${d.id}"]`);
    if (cb) state.options.instruments[d.id] = Boolean(cb.checked);
  }
}

/** Deep-ish clone of slot MIDI for save. */
function cloneMidi(midi) {
  if (!midi || typeof midi !== "object") return null;
  return {
    patternId: midi.patternId || "custom",
    octave: midi.octave ?? 3,
    key: midi.key || null,
    grid: Array.isArray(midi.grid)
      ? midi.grid.map((c) => (c && typeof c === "object" ? { ...c } : null))
      : null,
  };
}

function cloneMacros(macros) {
  if (!Array.isArray(macros)) return null;
  return macros.slice(0, 8).map((n) => {
    const v = Number(n);
    return Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 0;
  });
}

// ── Undo / redo (Ctrl+Z / Ctrl+Y) ───────────────────────────────────────────
const UNDO_LIMIT = 40;
/** @type {{ label: string, snap: object }[]} */
const undoStack = [];
/** @type {{ label: string, snap: object }[]} */
const redoStack = [];
/** Suppress push while restoring a snapshot */
let undoSuspended = false;
/** Coalesce rapid MIDI edits into one undo step */
let midiUndoCoalesce = { role: null, at: 0 };

function cloneSlotSnapshot(s) {
  if (!s || typeof s !== "object") return {};
  return {
    type: s.type || null,
    name: s.name || "",
    meta: s.meta || "",
    path: s.path || null,
    kind: s.kind || null,
    pack: s.pack || "",
    ext: s.ext || null,
    empty: Boolean(s.empty),
    locked: Boolean(s.locked),
    muted: Boolean(s.muted),
    solo: Boolean(s.solo),
    serumType: s.serumType || null,
    midi: cloneMidi(s.midi),
    macros: cloneMacros(s.macros),
  };
}

/** Capture tracks + session fields that user actions mutate. */
function captureDocSnapshot() {
  const slots = {};
  for (const id of state.trackOrder) {
    if (state.slots[id]) slots[id] = cloneSlotSnapshot(state.slots[id]);
  }
  return {
    trackOrder: [...state.trackOrder],
    trackSeq,
    slots,
    bpm: getBpm(),
    key: $("#key")?.value || "F minor",
    style: $("#style")?.value || "Techno",
  };
}

function pushUndo(label) {
  if (undoSuspended) return;
  undoStack.push({ label: label || "Edit", snap: captureDocSnapshot() });
  while (undoStack.length > UNDO_LIMIT) undoStack.shift();
  redoStack.length = 0;
  midiUndoCoalesce = { role: null, at: 0 };
}

/**
 * MIDI grid edits: one undo step per burst (same track within ~2.5s).
 * Snapshot is taken before the first edit in the burst.
 */
function pushMidiUndo(role) {
  if (undoSuspended) return;
  const now = Date.now();
  if (midiUndoCoalesce.role === role && now - midiUndoCoalesce.at < 2500) {
    midiUndoCoalesce.at = now;
    return;
  }
  undoStack.push({
    label: `MIDI · ${role}`,
    snap: captureDocSnapshot(),
  });
  while (undoStack.length > UNDO_LIMIT) undoStack.shift();
  redoStack.length = 0;
  midiUndoCoalesce = { role, at: now };
}

function restoreDocSnapshot(snap) {
  if (!snap) return;
  undoSuspended = true;
  try {
    stopAll();
    closeAllMidiEditors();
    const list = $("#slot-list");
    if (!list) return;
    list.innerHTML = "";
    state.trackOrder = [];
    state.slots = {};

    const bpmEl = $("#bpm");
    const keyEl = $("#key");
    const styleEl = $("#style");
    if (bpmEl && snap.bpm != null) bpmEl.value = String(snap.bpm);
    if (keyEl && snap.key) keyEl.value = snap.key;
    if (styleEl && snap.style != null) styleEl.value = snap.style;

    trackSeq = Number(snap.trackSeq) || 0;
    const order = Array.isArray(snap.trackOrder) ? snap.trackOrder : [];
    const slotsIn = snap.slots && typeof snap.slots === "object" ? snap.slots : {};

    for (const id of order) {
      const raw = slotsIn[id] || {};
      const type = String(raw.type || String(id).split("__")[0] || "kick").toLowerCase();
      state.trackOrder.push(id);
      state.slots[id] = {
        type,
        name: raw.name || (isSerumType(type) ? `Serum · ${type}` : "— empty —"),
        meta: raw.meta || "",
        path: raw.path || null,
        kind: raw.kind || null,
        pack: raw.pack || "",
        ext: raw.ext || null,
        empty: raw.empty != null ? Boolean(raw.empty) : !raw.path,
        locked: Boolean(raw.locked),
        muted: Boolean(raw.muted),
        solo: Boolean(raw.solo),
        serumType: raw.serumType || (isSerumType(type) ? type : "any"),
        midi: cloneMidi(raw.midi),
        macros: cloneMacros(raw.macros),
      };
      const art = buildSlotElement(id, type);
      list.appendChild(art);
      bindSlotElement(art);
      applySlot(id, { ...state.slots[id] });
      if (isSerumTrack(id)) {
        if (!state.slots[id].midi) ensureSlotMidi(id);
        const sel = $(".slot-role-select", art);
        if (sel && state.slots[id].serumType) {
          const st = state.slots[id].serumType;
          if (![...sel.options].some((o) => o.value === st)) {
            const optEl = document.createElement("option");
            optEl.value = st;
            optEl.textContent = st === "any" ? "ANY" : st.toUpperCase();
            sel.appendChild(optEl);
          }
          sel.value = st;
        }
      }
      syncLockUi(id);
      syncMuteUi(id);
      syncSoloUi(id);
    }

    markWaveDirty();
    drawWaveformFrame();
  } finally {
    undoSuspended = false;
  }
}

function performUndo() {
  if (!undoStack.length) {
    setStatus("Nothing to undo");
    return false;
  }
  const entry = undoStack.pop();
  redoStack.push({ label: entry.label, snap: captureDocSnapshot() });
  while (redoStack.length > UNDO_LIMIT) redoStack.shift();
  restoreDocSnapshot(entry.snap);
  setStatus(`Undo · ${entry.label}${undoStack.length ? "" : " · (stack empty)"}`);
  return true;
}

function performRedo() {
  if (!redoStack.length) {
    setStatus("Nothing to redo");
    return false;
  }
  const entry = redoStack.pop();
  undoStack.push({ label: entry.label, snap: captureDocSnapshot() });
  while (undoStack.length > UNDO_LIMIT) undoStack.shift();
  restoreDocSnapshot(entry.snap);
  setStatus(`Redo · ${entry.label}`);
  return true;
}

/** True when Ctrl+Z should leave native text editing alone. */
function isTextEntryTarget(el) {
  if (!el || el.disabled) return false;
  if (el.isContentEditable) return true;
  const tag = el.tagName;
  if (tag === "TEXTAREA") return true;
  if (tag === "INPUT") {
    const type = String(el.type || "text").toLowerCase();
    return ![
      "button",
      "checkbox",
      "radio",
      "range",
      "file",
      "color",
      "submit",
      "reset",
      "hidden",
    ].includes(type);
  }
  return false;
}

/** Snapshot current session for POST /api/loops. */
function serializeLoop(name) {
  const slots = {};
  for (const id of activeTrackIds()) {
    const s = state.slots[id] || {};
    slots[id] = {
      type: baseType(id),
      name: s.name || "",
      meta: s.meta || "",
      path: s.path || null,
      kind: s.kind || null,
      pack: s.pack || "",
      ext: s.ext || null,
      empty: Boolean(s.empty),
      locked: Boolean(s.locked),
      muted: Boolean(s.muted),
      solo: Boolean(s.solo),
      serumType: s.serumType || (isSerumTrack(id) ? baseType(id) : "any"),
      midi: cloneMidi(s.midi),
      macros: cloneMacros(s.macros),
    };
  }
  readSerumEngineOptionsFromDom();
  return {
    name: String(name || "").trim(),
    bpm: getBpm(),
    key: $("#key")?.value || "F minor",
    style: $("#style")?.value || "Techno",
    options: {
      filterRisers: getFilterRisers(),
      filterFactorySerum: getFilterFactorySerum(),
      serum1: state.options.serum1 !== false,
      serum2: state.options.serum2 !== false,
      instruments: { ...(state.options.instruments || defaultInstrumentsMap()) },
    },
    track_order: [...activeTrackIds()],
    slots,
    id: state.currentLoopId || null,
  };
}

function defaultLoopName() {
  const style = ($("#style")?.value || "Loop").trim() || "Loop";
  const key = ($("#key")?.value || "").trim();
  const bpm = getBpm();
  const parts = [style, key, `${bpm}bpm`].filter(Boolean);
  return parts.join(" · ");
}

function openSaveDialog() {
  const dlg = $("#save-dialog");
  const input = $("#save-name");
  if (!dlg || !input) return;
  input.value = state.currentLoopName || defaultLoopName();
  dlg.showModal();
  requestAnimationFrame(() => {
    input.focus();
    input.select();
  });
}

async function doSaveLoop(name) {
  const body = serializeLoop(name);
  if (!body.name) throw new Error("name required");
  if (!body.track_order.length) throw new Error("no tracks to save");
  setStatus("Saving…");
  const res = await api("/api/loops", {
    method: "POST",
    body: JSON.stringify(body),
  });
  state.currentLoopId = res.id || null;
  state.currentLoopName = res.name || body.name;
  setStatus(`Saved · ${state.currentLoopName}`);
  return res;
}

function closeAllMidiEditors() {
  for (const id of Object.keys(midiEditors)) {
    closeMidiEditor(id);
  }
}

/**
 * Rebuild track stack from a saved loop document.
 * @param {object} doc
 */
function applyLoadedLoop(doc) {
  const list = $("#slot-list");
  if (!list) return;
  pushUndo("Load loop");
  stopAll();
  closeAllMidiEditors();
  bufferCache.clear();

  list.innerHTML = "";
  state.trackOrder = [];
  state.slots = {};
  trackSeq = 0;

  const bpmEl = $("#bpm");
  const keyEl = $("#key");
  const styleEl = $("#style");
  if (bpmEl && doc.bpm != null) bpmEl.value = String(doc.bpm);
  if (keyEl && doc.key) keyEl.value = doc.key;
  if (styleEl && doc.style != null) styleEl.value = doc.style;

  const filterOn = Boolean(doc.options?.filterRisers);
  state.options.filterRisers = filterOn;
  const opt = $("#opt-filter-risers");
  if (opt) opt.checked = filterOn;
  // Serum engine checkboxes (default both on if omitted in older saves)
  const o = doc.options || {};
  state.options.serum1 = o.serum1 !== false && o.serum1 !== 0;
  state.options.serum2 = o.serum2 !== false && o.serum2 !== 0;
  state.options.filterFactorySerum = Boolean(o.filterFactorySerum);
  if (o.instruments && typeof o.instruments === "object") {
    state.options.instruments = {
      ...defaultInstrumentsMap(),
      ...o.instruments,
    };
    ensureInstrumentsState();
    syncInstrumentCheckboxesUi();
  }
  // Legacy per-track serumEngine on first track if options missing
  if (o.serum1 == null && o.serum2 == null) {
    const legacy = Object.values(doc.slots || {})[0]?.serumEngine;
    if (legacy === "s1") {
      state.options.serum1 = true;
      state.options.serum2 = false;
    } else if (legacy === "s2") {
      state.options.serum1 = false;
      state.options.serum2 = true;
    }
  }
  syncSerumEngineOptionsUi();
  syncFilterFactorySerumUi();

  const order = Array.isArray(doc.track_order) ? doc.track_order : [];
  const slotsIn = doc.slots && typeof doc.slots === "object" ? doc.slots : {};

  // Recover trackSeq so newTrackId stays unique after load
  for (const id of order) {
    const m = String(id).match(/__(\d+)$/);
    if (m) trackSeq = Math.max(trackSeq, Number(m[1]));
  }

  for (const id of order) {
    const raw = slotsIn[id] || {};
    const type = String(raw.type || String(id).split("__")[0] || "kick").toLowerCase();
    state.trackOrder.push(id);
    state.slots[id] = {
      type,
      name: raw.name || (isSerumType(type) ? `Serum · ${type}` : "— empty —"),
      meta: raw.meta || "",
      path: raw.path || null,
      kind: raw.kind || null,
      pack: raw.pack || "",
      ext: raw.ext || null,
      empty: raw.empty != null ? Boolean(raw.empty) : !raw.path,
      locked: Boolean(raw.locked),
      muted: Boolean(raw.muted),
      solo: Boolean(raw.solo),
      serumType: raw.serumType || (isSerumType(type) ? type : "any"),
      midi: cloneMidi(raw.midi),
      macros: cloneMacros(raw.macros),
    };
    const art = buildSlotElement(id, type);
    list.appendChild(art);
    bindSlotElement(art);
    applySlot(id, { ...state.slots[id] });
    if (isSerumTrack(id)) {
      if (!state.slots[id].midi) ensureSlotMidi(id);
      const sel = $(".slot-role-select", art);
      if (sel && state.slots[id].serumType) {
        const st = state.slots[id].serumType;
        if (![...sel.options].some((o) => o.value === st)) {
          const optEl = document.createElement("option");
          optEl.value = st;
          optEl.textContent = st === "any" ? "ANY" : st.toUpperCase();
          sel.appendChild(optEl);
        }
        sel.value = st;
      }
    }
    syncLockUi(id);
    syncMuteUi(id);
    syncSoloUi(id);
  }

  state.currentLoopId = doc.id || null;
  state.currentLoopName = doc.name || null;

  if (!order.length) {
    initDefaultTracks();
  }
}

function formatSavedAt(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return String(iso);
  }
}

async function refreshLoopsList() {
  const listEl = $("#loops-list");
  const emptyEl = $("#loops-empty");
  if (!listEl) return;
  listEl.innerHTML = "";
  const data = await api("/api/loops");
  const items = data.items || [];
  if (emptyEl) emptyEl.hidden = items.length > 0;
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "loop-item";
    row.setAttribute("role", "listitem");
    row.dataset.id = item.id || "";
    const meta = [
      item.bpm != null ? `${item.bpm} BPM` : null,
      item.key || null,
      item.style || null,
      item.track_count != null ? `${item.track_count} trk` : null,
      formatSavedAt(item.saved_at),
    ]
      .filter(Boolean)
      .join(" · ");
    row.innerHTML = `
      <div class="loop-item-body">
        <div class="loop-item-name"></div>
        <div class="loop-item-meta"></div>
      </div>
      <div class="loop-item-actions">
        <button type="button" class="btn primary loop-load" data-tip="Load this loop">Load</button>
        <button type="button" class="btn ghost loop-delete" data-tip="Delete this save">🗑️</button>
      </div>
    `;
    $(".loop-item-name", row).textContent = item.name || "Untitled";
    $(".loop-item-meta", row).textContent = meta;
    $(".loop-load", row)?.addEventListener("click", () => {
      doLoadLoop(item.id).catch((e) => setStatus(`Load failed: ${e.message}`));
    });
    $(".loop-delete", row)?.addEventListener("click", () => {
      doDeleteLoop(item.id, item.name).catch((e) =>
        setStatus(`Delete failed: ${e.message}`)
      );
    });
    listEl.appendChild(row);
  }
}

async function openMyLoopsDialog() {
  const dlg = $("#loops-dialog");
  if (!dlg) return;
  setStatus("Loading saves…");
  try {
    await refreshLoopsList();
    setStatus("My Loops");
  } catch (e) {
    setStatus(`My Loops failed: ${e.message}`);
  }
  dlg.showModal();
}

async function doLoadLoop(loopId) {
  if (!loopId) return;
  setStatus("Loading loop…");
  const doc = await api(`/api/loops/${encodeURIComponent(loopId)}`);
  applyLoadedLoop(doc);
  $("#loops-dialog")?.close();
  setStatus(`Loaded · ${doc.name || loopId} — press Play`);
}

async function doDeleteLoop(loopId, name) {
  if (!loopId) return;
  const label = name || loopId;
  if (!window.confirm(`Delete saved loop “${label}”?`)) return;
  await api(`/api/loops/${encodeURIComponent(loopId)}`, { method: "DELETE" });
  if (state.currentLoopId === loopId) {
    state.currentLoopId = null;
  }
  await refreshLoopsList();
  setStatus(`Deleted · ${label}`);
}

function initUiChrome() {
  const bpmInput = $("#bpm");
  if (bpmInput) {
    bpmInput.addEventListener("input", onBpmInput);
    bpmInput.addEventListener("change", onBpmInput);
  }

  ensureInstrumentsState();
  renderInstrumentCheckboxes();
  // Tracks built after settings load in init() so saved instrument prefs apply

  $("#btn-generate")?.addEventListener("click", () => {
    doGenerate().catch((e) => setStatus(`Generate failed: ${e.message}`));
  });

  $("#btn-options")?.addEventListener("click", () => {
    const open = $("#options-panel")?.hasAttribute("hidden");
    setOptionsPanelOpen(Boolean(open));
  });
  $("#btn-options-close")?.addEventListener("click", () => {
    setOptionsPanelOpen(false);
  });
  $("#opt-filter-risers")?.addEventListener("change", (ev) => {
    state.options.filterRisers = Boolean(ev.target.checked);
    setStatus(
      state.options.filterRisers
        ? "Options · filter risers ON"
        : "Options · filter risers OFF"
    );
    scheduleSaveUserSettings({ immediate: true });
  });
  $("#opt-filter-factory-serum")?.addEventListener("change", (ev) => {
    state.options.filterFactorySerum = Boolean(ev.target.checked);
    setStatus(
      state.options.filterFactorySerum
        ? "Options · factory Serum OFF (Splice/User only)"
        : "Options · factory Serum allowed"
    );
    scheduleSaveUserSettings({ immediate: true });
  });
  const onSerumOpt = () => {
    readSerumEngineOptionsFromDom();
    const eng = getSerumEngine();
    setStatus(`Options · ${serumEngineLabel(eng)} for Generate / dice`);
    scheduleSaveUserSettings({ immediate: true });
  };
  $("#opt-serum1")?.addEventListener("change", onSerumOpt);
  $("#opt-serum2")?.addEventListener("change", onSerumOpt);
  syncSerumEngineOptionsUi();
  syncFilterFactorySerumUi();

  // Session fields also persist as user settings
  $("#bpm")?.addEventListener("change", () => scheduleSaveUserSettings());
  $("#key")?.addEventListener("change", () => scheduleSaveUserSettings({ immediate: true }));
  $("#style")?.addEventListener("change", () => scheduleSaveUserSettings());
  $("#style")?.addEventListener("blur", () => scheduleSaveUserSettings({ immediate: true }));

  $("#btn-add-track")?.addEventListener("click", () => {
    const type = $("#add-track-type")?.value || "bass";
    addTrack(type);
  });

  $("#btn-play")?.addEventListener("click", () => togglePlay());
  updatePlayButton();

  // Space = play/stop (skip when typing in fields)
  document.addEventListener("keydown", (ev) => {
    if (ev.code !== "Space" && ev.key !== " ") return;
    const t = ev.target;
    if (
      t &&
      (t.tagName === "INPUT" ||
        t.tagName === "TEXTAREA" ||
        t.tagName === "SELECT" ||
        t.isContentEditable)
    ) {
      return;
    }
    ev.preventDefault();
    togglePlay();
  });

  // Ctrl/Cmd+Z undo · Ctrl/Cmd+Y or Ctrl/Cmd+Shift+Z redo
  document.addEventListener("keydown", (ev) => {
    const mod = ev.ctrlKey || ev.metaKey;
    if (!mod) return;
    if (isTextEntryTarget(ev.target)) return;
    const key = String(ev.key || "").toLowerCase();
    if (key === "z" && !ev.shiftKey) {
      ev.preventDefault();
      performUndo();
      return;
    }
    if (key === "y" || (key === "z" && ev.shiftKey)) {
      ev.preventDefault();
      performRedo();
    }
  });

  $("#btn-shuffle")?.addEventListener("click", () => {
    doGenerate()
      .then(() => setStatus("Shuffled unlocked tracks"))
      .catch((e) => setStatus(`Shuffle failed: ${e.message}`));
  });

  $("#btn-save")?.addEventListener("click", () => openSaveDialog());
  $("#btn-my-loops")?.addEventListener("click", () => {
    openMyLoopsDialog().catch((e) => setStatus(`My Loops failed: ${e.message}`));
  });
  $("#loops-close")?.addEventListener("click", () => $("#loops-dialog")?.close());

  $("#save-cancel")?.addEventListener("click", () => $("#save-dialog")?.close());
  const saveForm = $("#save-form");
  saveForm?.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const name = ($("#save-name")?.value || "").trim();
    if (!name) {
      setStatus("Enter a name for this loop");
      return;
    }
    doSaveLoop(name)
      .then(() => $("#save-dialog")?.close())
      .catch((e) => setStatus(`Save failed: ${e.message}`));
  });

  const dialog = $("#library-dialog");
  $("#btn-library")?.addEventListener("click", () => dialog?.showModal());
  $("#dialog-scan")?.addEventListener("click", () => {
    doScan()
      .then(() => dialog?.close())
      .catch((e) => setStatus(`Scan failed: ${e.message}`));
  });
  $("#btn-rescan")?.addEventListener("click", () => {
    doScan().catch((e) => setStatus(`Scan failed: ${e.message}`));
  });
  $("#btn-export")?.addEventListener("click", () => {
    setStatus("Export not implemented yet");
  });
  $("#btn-open-export")?.addEventListener("click", () => {
    api("/api/export/open", { method: "POST", body: "{}" })
      .then((r) => setStatus(`Opened export folder · ${r.path || "exports"}`))
      .catch((e) => setStatus(`Open folder failed: ${e.message}`));
  });
}

async function init() {
  initUiChrome();
  initMidiEditorUi();
  initWaveOverview();
  initBottomTips();

  if (isFileProtocol()) {
    setStatus(
      "Opened as a file — start the server and use http://127.0.0.1:8000"
    );
    return;
  }

  try {
    await api("/api/health");
    try {
      await loadUserSettings();
    } catch (e) {
      console.warn("settings load failed:", e.message || e);
      ensureInstrumentsState();
    }
    initDefaultTracks();
    await loadLibrary();
    await doGenerate();
  } catch (e) {
    setStatus(
      `Backend not reachable: ${e.message}. Run: python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000`
    );
  }
}

document.addEventListener("DOMContentLoaded", init);
