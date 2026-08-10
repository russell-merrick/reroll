"""
Transport / Serum cutover math (source of truth for unit tests).

Mirrors frontend app.js LOOP_BARS + offset helpers so we can catch sync
regressions without Web Audio or ears.
"""

from __future__ import annotations

from dataclasses import dataclass

# Keep in sync with frontend `const LOOP_BARS`
LOOP_BARS = 4
STEPS_PER_BAR = 16


def cycle_steps(bars: int = LOOP_BARS) -> int:
    return max(1, int(bars) * STEPS_PER_BAR)


def sec_per_16th(bpm: float) -> float:
    b = float(bpm)
    if b <= 0:
        raise ValueError("bpm must be positive")
    return 60.0 / b / 4.0


def cycle_sec(bpm: float, bars: int = LOOP_BARS) -> float:
    return cycle_steps(bars) * sec_per_16th(bpm)


def quarter_note_hits_per_loop(bars: int = LOOP_BARS) -> int:
    """Kick on every quarter: 4 per bar."""
    return int(bars) * 4


def kick_hit_steps(bars: int = LOOP_BARS) -> list[int]:
    """16th-step indices where the default kick pattern fires (every quarter)."""
    steps: list[int] = []
    total = cycle_steps(bars)
    for s in range(total):
        if s % 4 == 0:
            steps.append(s)
    return steps


def serum_offset_for_step(
    buffer_duration_sec: float,
    step_in_cycle: int,
    *,
    bars: int = LOOP_BARS,
) -> float:
    """
    Seek into a full-cycle bounce so mid-loop cutover stays phase-locked to kick.
    Mirrors frontend serumOffsetForStep().
    """
    cycle = cycle_steps(bars)
    if buffer_duration_sec <= 0 or cycle <= 0:
        return 0.0
    step = step_in_cycle % cycle
    if step < 0:
        step += cycle
    if step <= 0:
        return 0.0
    return min(buffer_duration_sec * 0.999, (step / cycle) * buffer_duration_sec)


def remain_steps(step_in_cycle: int, *, bars: int = LOOP_BARS) -> int:
    cycle = cycle_steps(bars)
    step = step_in_cycle % cycle
    if step < 0:
        step += cycle
    return max(1, cycle - step)


def remain_sec(step_in_cycle: int, bpm: float, *, bars: int = LOOP_BARS) -> float:
    return remain_steps(step_in_cycle, bars=bars) * sec_per_16th(bpm)


def playback_rate_for_stem(buffer_duration_sec: float, cycle_duration_sec: float) -> float:
    """
    Allowed micro-trim only; large stretch would pitch-shift (forbidden).
    Mirrors scheduleSerumStemRole rate logic.
    """
    if buffer_duration_sec <= 0.05 or cycle_duration_sec <= 0:
        return 1.0
    ratio = buffer_duration_sec / cycle_duration_sec
    if 0.97 < ratio < 1.03:
        return ratio
    return 1.0


def stem_bpm_matches(stem_bpm: float, session_bpm: float, *, tol: float = 0.25) -> bool:
    return abs(float(stem_bpm) - float(session_bpm)) <= tol


def truncate_display_name(name: str, max_len: int = 50) -> str:
    """Mirrors frontend truncateDisplayName."""
    s = (name or "").strip()
    if not s:
        return "—"
    if len(s) <= max_len:
        return s
    if max_len <= 3:
        return s[:max_len]
    return s[: max_len - 3] + "..."


@dataclass(frozen=True)
class CutoverPlan:
    step_in_cycle: int
    offset_sec: float
    remain_sec: float
    on_grid: bool  # True if start should share kick's scheduleStep `when`


def plan_cutover(
    step: int,
    buffer_duration_sec: float,
    bpm: float,
    *,
    bars: int = LOOP_BARS,
) -> CutoverPlan:
    """Full cutover plan for applying a new stem at transport step `step`."""
    cycle = cycle_steps(bars)
    step_in = step % cycle
    if step_in < 0:
        step_in += cycle
    return CutoverPlan(
        step_in_cycle=step_in,
        offset_sec=serum_offset_for_step(buffer_duration_sec, step_in, bars=bars),
        remain_sec=remain_sec(step_in, bpm, bars=bars),
        on_grid=True,
    )
