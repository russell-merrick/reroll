"""User settings read/write normalization."""

from __future__ import annotations

import json
from pathlib import Path

from backend import app as backend_app


def test_default_settings_shape(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(backend_app, "SETTINGS_PATH", tmp_path / "user_settings.json")
    d = backend_app._default_settings()
    assert d["filterRisers"] is True
    assert d["serum1"] is True
    assert d["serum2"] is True
    assert d["filterFactorySerum"] is False
    assert isinstance(d["instruments"], dict)
    assert d["sampleRoots"] == []
    assert d["serumRoots"] == []
    assert d["theme"] == "dark"
    assert d["bars"] == 1
    assert 60 <= d["bpm"] <= 200


def test_write_read_roundtrip(tmp_path: Path, monkeypatch):
    path = tmp_path / "user_settings.json"
    monkeypatch.setattr(backend_app, "SETTINGS_PATH", path)
    saved = backend_app._write_user_settings(
        {
            "bpm": 155,
            "key": "A minor",
            "style": "Hard Techno",
            "filterRisers": False,
            "filterFactorySerum": True,
            "serum1": False,
            "serum2": True,
            "instruments": {"kick": True, "pads": False},
            "serumRoots": [r"G:\Other computers\Snowy\music\serum presets"],
        }
    )
    assert path.is_file()
    loaded = backend_app._read_user_settings()
    assert loaded["bpm"] == 155
    assert loaded["key"] == "A minor"
    assert loaded["filterFactorySerum"] is True
    assert loaded["serum1"] is False
    assert loaded["instruments"]["kick"] is True
    assert saved["style"] == "Hard Techno"
    assert loaded["serumRoots"] == [r"G:\Other computers\Snowy\music\serum presets"]


def test_write_preserves_roots_when_omitted(tmp_path: Path, monkeypatch):
    path = tmp_path / "user_settings.json"
    monkeypatch.setattr(backend_app, "SETTINGS_PATH", path)
    backend_app._write_user_settings(
        {"serumRoots": [r"D:\presets"], "sampleRoots": [r"D:\samples"]}
    )
    backend_app._write_user_settings({"bpm": 128})
    loaded = backend_app._read_user_settings()
    assert loaded["bpm"] == 128
    assert loaded["serumRoots"] == [r"D:\presets"]
    assert loaded["sampleRoots"] == [r"D:\samples"]


def test_bars_snapped_to_1_2_4(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(backend_app, "SETTINGS_PATH", tmp_path / "s.json")
    assert backend_app._write_user_settings({"bars": 1})["bars"] == 1
    assert backend_app._write_user_settings({"bars": 2})["bars"] == 2
    assert backend_app._write_user_settings({"bars": 3})["bars"] == 4
    assert backend_app._write_user_settings({"bars": 4})["bars"] == 4
    assert backend_app._write_user_settings({"bars": 0})["bars"] == 1
    assert backend_app._write_user_settings({"bars": 8})["bars"] == 4


def test_bpm_clamped(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(backend_app, "SETTINGS_PATH", tmp_path / "s.json")
    out = backend_app._write_user_settings({"bpm": 999})
    assert out["bpm"] == 200
    out2 = backend_app._write_user_settings({"bpm": 10})
    assert out2["bpm"] == 60


def test_missing_file_returns_defaults(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(backend_app, "SETTINGS_PATH", tmp_path / "missing.json")
    d = backend_app._read_user_settings()
    assert d["filterRisers"] is True


def test_theme_normalized(tmp_path: Path, monkeypatch):
    path = tmp_path / "user_settings.json"
    monkeypatch.setattr(backend_app, "SETTINGS_PATH", path)
    out = backend_app._write_user_settings({"theme": "NEON"})
    assert out["theme"] == "neon"
    bad = backend_app._write_user_settings({"theme": "hotdog"})
    assert bad["theme"] == "dark"
