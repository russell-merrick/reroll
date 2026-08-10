"""SQLite catalog persistence."""

from __future__ import annotations

from pathlib import Path

from backend.catalog import Asset, Catalog
from backend.persist import load_catalog, save_catalog


def test_save_and_load_roundtrip(tmp_path: Path):
    cat = Catalog()
    cat.sample_roots = [r"C:\samples"]
    cat.serum_roots = [r"C:\serum"]
    cat.scanned = True
    cat.samples.append(
        Asset(
            path=r"C:\samples\kick.wav",
            name="kick.wav",
            kind="sample",
            role="kick",
            ext=".wav",
            pack="pack-a",
        )
    )
    cat.serum.append(
        Asset(
            path=r"C:\serum\bass.fxp",
            name="bass.fxp",
            kind="serum",
            role="bass",
            ext=".fxp",
            category="bass",
            origin="user",
        )
    )
    db = tmp_path / "library.db"
    info = save_catalog(cat, db)
    assert info["ok"]
    assert info["assets"] == 2

    loaded = load_catalog(db)
    assert loaded is not None
    assert loaded.scanned
    assert len(loaded.samples) == 1
    assert len(loaded.serum) == 1
    assert loaded.samples[0].role == "kick"
    assert loaded.serum[0].category == "bass"
    assert loaded.sample_roots == [r"C:\samples"]


def test_load_missing_returns_none(tmp_path: Path):
    assert load_catalog(tmp_path / "nope.db") is None
