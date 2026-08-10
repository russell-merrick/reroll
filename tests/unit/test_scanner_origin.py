"""Serum bank origin classification (factory vs Splice vs User)."""

from __future__ import annotations

from pathlib import Path

from backend.catalog import Asset
from backend.scanner import is_factory_serum, serum_origin
from tests.conftest import make_asset


def test_serum2_factory_path():
    root = Path(r"C:\Users\x\Documents\Xfer\Serum 2 Presets\Presets")
    p = root / "Factory" / "Bass" / "Hard" / "BA_stock.SerumPreset"
    assert serum_origin(p, root) == "factory"


def test_serum2_splice_path():
    root = Path(r"C:\Users\x\Documents\Xfer\Serum 2 Presets\Presets")
    p = root / "Splice" / "Pack" / "BA_mine.SerumPreset"
    assert serum_origin(p, root) == "splice"


def test_serum2_user_path():
    root = Path(r"C:\Users\x\Documents\Xfer\Serum 2 Presets\Presets")
    p = root / "User" / "BA_custom.SerumPreset"
    assert serum_origin(p, root) == "user"


def test_serum1_factory_category():
    root = Path(r"C:\Users\x\Documents\Xfer\Serum Presets\Presets")
    p = root / "Bass" / "BA_stock.fxp"
    assert serum_origin(p, root) == "factory"


def test_serum1_splice():
    root = Path(r"C:\Users\x\Documents\Xfer\Serum Presets\Presets")
    p = root / "Splice" / "BA_mine.fxp"
    assert serum_origin(p, root) == "splice"


def test_nested_splice_under_s1_presets_counts_as_splice():
    """S2 layout: S1 Presets/Splice/... should not be filtered as factory."""
    root = Path(r"C:\Users\x\Documents\Xfer\Serum 2 Presets\Presets")
    p = root / "S1 Presets" / "Splice" / "Fume" / "pad.SerumPreset"
    assert serum_origin(p, root) == "splice"


def test_is_factory_serum_uses_origin_tag():
    factory = make_asset(
        path=r"C:\x\Factory\a.SerumPreset",
        kind="serum",
        ext=".serumpreset",
        origin="factory",
    )
    splice = make_asset(
        path=r"C:\x\Splice\a.SerumPreset",
        kind="serum",
        ext=".serumpreset",
        origin="splice",
    )
    assert is_factory_serum(factory)
    assert not is_factory_serum(splice)


def test_is_factory_serum_ignores_samples():
    a = make_asset(path=r"C:\x\kick.wav", kind="sample", role="kick")
    assert not is_factory_serum(a)
