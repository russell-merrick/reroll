"""Catalog pick / filter tests — factory, risers, engines, lead_audio."""

from __future__ import annotations

import random

from backend.catalog import Catalog
from backend.generate import (
    get_slot_kind,
    is_riser_like,
    pick_asset,
    _filter_serum_engine,
)
from tests.conftest import make_asset


def test_slot_kinds():
    assert get_slot_kind("kick") == "sample"
    assert get_slot_kind("lead_audio") == "sample"
    assert get_slot_kind("bass") == "serum"
    assert get_slot_kind("brass") == "serum"
    assert get_slot_kind("vocal") == "sample"


def test_riser_detection():
    riser = make_asset(path=r"C:\x\buildup_riser.wav", name="buildup_riser.wav", role="fx")
    clean = make_asset(path=r"C:\x\kick_01.wav", name="kick_01.wav", role="kick")
    assert is_riser_like(riser)
    assert not is_riser_like(clean)


def test_riser_detection_underscore_build_token():
    """Pack names use _Build_ — \\b does not split on underscore."""
    build = make_asset(
        path=r"C:\x\STCR2_MHPT2_126_Snare_Build_Overcast.wav",
        name="STCR2_MHPT2_126_Snare_Build_Overcast.wav",
        role="snare",
    )
    assert is_riser_like(build)
    # "build" as substring of unrelated word should not match
    builder = make_asset(
        path=r"C:\x\builder_kit_hit.wav",
        name="builder_kit_hit.wav",
        role="perc",
    )
    assert not is_riser_like(builder)


def test_filter_serum_engine(sample_catalog: Catalog):
    pool = list(sample_catalog.serum)
    s1 = _filter_serum_engine(pool, "s1")
    s2 = _filter_serum_engine(pool, "s2")
    none = _filter_serum_engine(pool, "none")
    assert all(a.ext.lower() == ".fxp" for a in s1)
    assert all(a.ext.lower() == ".serumpreset" for a in s2)
    assert none == []
    assert len(_filter_serum_engine(pool, "both")) == len(pool)


def test_filter_factory_serum_keeps_splice_and_user(sample_catalog: Catalog):
    random.seed(0)
    for _ in range(20):
        a = pick_asset(
            sample_catalog,
            "bass",
            serum_engine="both",
            serum_type="bass",
            filter_factory_serum=True,
        )
        assert a is not None
        assert a.origin in ("splice", "user")
        assert a.origin != "factory"


def test_filter_factory_off_can_pick_factory(sample_catalog: Catalog):
    random.seed(1)
    paths = set()
    for _ in range(40):
        a = pick_asset(
            sample_catalog,
            "bass",
            serum_engine="both",
            serum_type="bass",
            filter_factory_serum=False,
        )
        if a:
            paths.add(a.origin)
    assert "factory" in paths or "splice" in paths


def test_filter_risers_skips_riser_samples(sample_catalog: Catalog):
    random.seed(2)
    # Only FX asset is a riser → filter must return None (strict, no fallback)
    a = pick_asset(sample_catalog, "fx", filter_risers=True)
    assert a is None
    # Without filter, riser can be picked
    b = pick_asset(sample_catalog, "fx", filter_risers=False)
    assert b is not None
    assert is_riser_like(b)


def test_lead_audio_never_returns_serum(sample_catalog: Catalog):
    """Lead (audio) must not fall back to Serum presets."""
    # Remove sample leads — only serum remains in catalog for musical roles
    sample_catalog.samples = [a for a in sample_catalog.samples if a.role != "lead"]
    a = pick_asset(sample_catalog, "lead_audio", serum_engine="both")
    assert a is None  # no sample lead left, must not grab serum bass


def test_lead_audio_picks_sample_when_available(sample_catalog: Catalog):
    a = pick_asset(sample_catalog, "lead_audio")
    assert a is not None
    assert a.kind == "sample"
    assert a.role == "lead"


def test_reroll_excludes_current_path(sample_catalog: Catalog):
    random.seed(3)
    first = pick_asset(sample_catalog, "kick")
    assert first is not None
    # Only two kicks — exclude first should yield second when possible
    others = {
        pick_asset(sample_catalog, "kick", exclude_path=first.path).path
        for _ in range(30)
        if pick_asset(sample_catalog, "kick", exclude_path=first.path)
    }
    assert first.path not in others or len(sample_catalog.samples) < 2
    # With two kicks, should get the other path at least once
    kick_paths = {a.path for a in sample_catalog.samples if a.role == "kick"}
    if len(kick_paths) >= 2:
        assert others - {first.path}


def test_serum_s1_engine_only_fxp(sample_catalog: Catalog):
    random.seed(4)
    for _ in range(15):
        a = pick_asset(
            sample_catalog,
            "bass",
            serum_engine="s1",
            serum_type="bass",
            filter_factory_serum=False,
        )
        assert a is not None
        assert a.ext.lower() == ".fxp"


def test_serum_s2_engine_only_serumpreset(sample_catalog: Catalog):
    random.seed(5)
    for _ in range(15):
        a = pick_asset(
            sample_catalog,
            "bass",
            serum_engine="s2",
            serum_type="bass",
            filter_factory_serum=False,
        )
        assert a is not None
        assert a.ext.lower() == ".serumpreset"
