"""Custom + default library root merging / flat-folder classify."""

from __future__ import annotations

from pathlib import Path

from backend.scanner import (
    DEFAULT_SERUM_ROOTS,
    classify_serum,
    merge_scan_roots,
    pack_name,
    serum_category,
    serum_origin,
)


def test_merge_scan_roots_defaults_then_extras(tmp_path: Path):
    extra = tmp_path / "my_presets"
    extra.mkdir()
    roots = merge_scan_roots([str(extra)], DEFAULT_SERUM_ROOTS)
    assert roots[0] == DEFAULT_SERUM_ROOTS[0].expanduser().resolve()
    assert roots[-1] == extra.resolve()


def test_merge_dedupes_case_insensitive(tmp_path: Path):
    d = tmp_path / "a"
    d.mkdir()
    roots = merge_scan_roots([str(d), str(d).upper()], [d])
    assert len(roots) == 1


def test_flat_dump_category_and_origin(tmp_path: Path):
    root = tmp_path / "serum presets"
    root.mkdir()
    fxp = root / "BASS - Rolling 2.fxp"
    fxp.write_bytes(b"x")
    assert classify_serum(fxp, root) == "bass"
    assert serum_category(fxp, root) == "bass"
    assert serum_origin(fxp, root) == "user"
    assert pack_name(fxp, root) == "serum presets"


def test_underscore_bass_in_filename(tmp_path: Path):
    root = tmp_path / "dump"
    root.mkdir()
    p = root / "TSP_S2GE_Bass_seventh.SerumPreset"
    p.write_bytes(b"x")
    assert classify_serum(p, root) == "bass"
    assert serum_category(p, root) == "bass"
    ba = root / "7S_TALES2_BA_Carpet.SerumPreset"
    ba.write_bytes(b"x")
    assert classify_serum(ba, root) == "bass"
