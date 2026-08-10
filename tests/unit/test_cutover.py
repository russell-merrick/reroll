"""
Mid-loop Serum cutover rules (state machine).

Protects against: change octave/pattern → audio restarts from t=0 while kick
is mid-loop (the desync you hear).
"""

from __future__ import annotations

from backend.timing import (
    LOOP_BARS,
    cycle_sec,
    cycle_steps,
    plan_cutover,
    playback_rate_for_stem,
    serum_offset_for_step,
    stem_bpm_matches,
)


def test_mid_loop_cutover_never_zero_offset():
    bars = LOOP_BARS
    cycle = cycle_steps(bars)
    buf = cycle_sec(140, bars)
    for step in range(1, cycle):
        plan = plan_cutover(step, buf, 140, bars=bars)
        assert plan.offset_sec > 0, f"step {step} must seek into bounce"
        assert plan.on_grid is True


def test_cycle_boundary_offset_zero():
    buf = cycle_sec(140)
    for step in (0, 64, 128, 256):
        # only step 0 within 4-bar cycle of 64; use modulo via plan_cutover
        plan = plan_cutover(step, buf, 140)
        if step % 64 == 0:
            assert plan.offset_sec == 0.0


def test_cutover_not_at_wall_clock_now():
    """Documented contract: cutover when must be scheduleStep `when`, not now+ε."""
    plan = plan_cutover(20, 8.0, 140)
    assert plan.on_grid is True  # caller must use grid `when`


def test_stale_bpm_detected():
    assert not stem_bpm_matches(120, 140)
    # schedule layer should refuse stale stems
    assert stem_bpm_matches(140, 140.0)


def test_no_pitch_stretch_when_bpm_mismatched_length():
    # Bounce at 120, session 140 → duration ratio far from 1
    buf_120 = cycle_sec(120)
    cycle_140 = cycle_sec(140)
    rate = playback_rate_for_stem(buf_120, cycle_140)
    assert rate == 1.0  # do not stretch; re-bounce instead


def test_offset_scales_with_buffer_duration():
    """Seek uses fraction of bounce length (matches rendered timeline)."""
    a = serum_offset_for_step(10.0, 32)  # half of 64
    b = serum_offset_for_step(20.0, 32)
    assert abs(a - 5.0) < 1e-9
    assert abs(b - 10.0) < 1e-9
