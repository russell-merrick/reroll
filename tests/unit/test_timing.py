"""Transport / cutover math — catches mid-loop desync regressions."""

from __future__ import annotations

import pytest

from backend.timing import (
    LOOP_BARS,
    cycle_sec,
    cycle_steps,
    kick_hit_steps,
    plan_cutover,
    playback_rate_for_stem,
    quarter_note_hits_per_loop,
    remain_sec,
    sec_per_16th,
    serum_offset_for_step,
    stem_bpm_matches,
    truncate_display_name,
)


def test_loop_bars_is_four():
    assert LOOP_BARS == 4
    assert cycle_steps() == 64
    assert quarter_note_hits_per_loop() == 16


def test_sec_per_16th_at_common_bpms():
    assert abs(sec_per_16th(120) - 0.125) < 1e-9
    assert abs(sec_per_16th(140) - (60 / 140 / 4)) < 1e-9
    # Faster BPM → shorter steps
    assert sec_per_16th(160) < sec_per_16th(120)


def test_sec_per_16th_rejects_bad_bpm():
    with pytest.raises(ValueError):
        sec_per_16th(0)
    with pytest.raises(ValueError):
        sec_per_16th(-10)


def test_kick_hit_steps_are_quarters_only():
    hits = kick_hit_steps(4)
    assert hits[0] == 0
    assert all(h % 4 == 0 for h in hits)
    assert len(hits) == 16
    # First bar: 0,4,8,12
    assert hits[:4] == [0, 4, 8, 12]


def test_serum_offset_zero_at_cycle_start():
    buf = cycle_sec(140, 4)
    assert serum_offset_for_step(buf, 0) == 0.0


def test_serum_offset_mid_cycle_not_zero():
    """Regression: cutover mid-loop must not restart bounce from t=0."""
    buf = cycle_sec(140, 4)
    mid = 32  # halfway through 64-step cycle
    off = serum_offset_for_step(buf, mid)
    assert off > 0
    assert abs(off - buf * 0.5) < 1e-9


def test_serum_offset_last_step_near_end():
    buf = cycle_sec(140, 4)
    off = serum_offset_for_step(buf, 63)
    assert off > buf * 0.9
    assert off < buf


def test_remain_is_positive_across_cycle():
    bpm = 140
    bars = 4
    from backend.timing import remain_steps

    for step in (0, 1, 16, 32, 63):
        rem = remain_sec(step, bpm, bars=bars)
        assert rem > 0
        assert rem == pytest.approx(remain_steps(step, bars=bars) * sec_per_16th(bpm))


def test_plan_cutover_on_grid_and_mid_cycle():
    buf = 8.0
    p0 = plan_cutover(0, buf, 140)
    assert p0.on_grid
    assert p0.offset_sec == 0.0

    p20 = plan_cutover(20, buf, 140)
    assert p20.step_in_cycle == 20
    assert p20.offset_sec > 0
    assert p20.remain_sec < cycle_sec(140)


def test_playback_rate_no_large_stretch():
    """BPM change must not pitch-shift via big playbackRate."""
    cycle = cycle_sec(140)
    # Same length → ~1
    assert abs(playback_rate_for_stem(cycle, cycle) - 1.0) < 1e-9
    # Slightly off → micro trim allowed
    r = playback_rate_for_stem(cycle * 1.01, cycle)
    assert 0.97 < r < 1.03
    # Large mismatch (old BPM bounce) → force rate 1 (re-bounce instead)
    assert playback_rate_for_stem(cycle * 1.2, cycle) == 1.0


def test_stem_bpm_match():
    assert stem_bpm_matches(140, 140)
    assert stem_bpm_matches(140.1, 140)
    assert not stem_bpm_matches(120, 140)


def test_truncate_display_name():
    assert truncate_display_name("") == "—"
    assert truncate_display_name("short") == "short"
    long = "a" * 60
    out = truncate_display_name(long, 50)
    assert len(out) == 50
    assert out.endswith("...")
    assert out.startswith("a" * 47)
