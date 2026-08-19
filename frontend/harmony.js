/**
 * Display-only harmony helpers. Python /api/harmony/* expands MIDI.
 */

const HARMONY_PAD_TYPES = new Set(["pad", "pads", "strings", "chorus", "keys"]);
const HARMONY_LEAD_TYPES = new Set([
  "lead",
  "synth",
  "arp",
  "pluck",
  "seq",
  "hoover",
  "guitar",
  "brass",
]);

/** Mirror of backend.harmony.harmony_role — bass | pad | lead | null. */
function harmonyRole(trackType) {
  const t = String(trackType || "")
    .split("__")[0]
    .trim()
    .toLowerCase();
  if (t === "bass") return "bass";
  if (HARMONY_PAD_TYPES.has(t)) return "pad";
  if (HARMONY_LEAD_TYPES.has(t)) return "lead";
  return null;
}

function formatRomans(progression) {
  if (!progression) return "";
  const chords = progression.chords;
  if (Array.isArray(chords) && chords.length) {
    return chords.map((c) => (c && c.roman) || "—").join("–");
  }
  return progression.label || "";
}

function tonicMinorLabel(key) {
  const raw = String(key || "C").trim();
  const m = raw.match(/^([A-G])(#|b)?/i);
  if (!m) return "C minor";
  return `${m[1].toUpperCase()}${m[2] || ""} minor`;
}

function themeSubtitle(progression, sessionKey) {
  if (!progression) return "";
  const aeolian = progression.key || tonicMinorLabel(sessionKey);
  const session = String(sessionKey || "").trim();
  const style = progression.style_used || "";
  if (/major/i.test(session)) {
    const tonic = String(aeolian).replace(/\s*minor$/i, "");
    const aeolianLabel = `${tonic} Aeolian (session ${session})`;
    return style ? `${aeolianLabel} · ${style}` : aeolianLabel;
  }
  return [aeolian, style].filter(Boolean).join(" · ");
}
