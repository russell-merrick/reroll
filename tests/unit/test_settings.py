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
