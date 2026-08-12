"""Shared fixtures for unit tests (no live Serum required)."""

from __future__ import annotations

import pytest

from backend.catalog import Asset, Catalog


def make_asset(
    *,
    path: str,
    name: str | None = None,
    kind: str = "sample",
    role: str = "kick",
    ext: str | None = None,
    pack: str = "",
    category: str = "",
    origin: str = "",
) -> Asset:
    if ext is None:
        ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ".wav"
    return Asset(
        path=path,
        name=name or path.replace("\\", "/").rsplit("/", 1)[-1],
        kind=kind,
        role=role,
        ext=ext if ext.startswith(".") else f".{ext}",
        pack=pack,
        parent="",
        category=category,
        origin=origin,
    )


@pytest.fixture
def empty_catalog() -> Catalog:
    c = Catalog()
    c.scanned = True
    return c


@pytest.fixture
def sample_catalog() -> Catalog:
    """Small in-memory catalog for generate/pick tests."""
    c = Catalog()
    c.scanned = True
    c.samples = [
        make_asset(path=r"C:\lib\kicks\kick_01.wav", role="kick", pack="PackA"),
        make_asset(path=r"C:\lib\kicks\kick_02.wav", role="kick", pack="PackA"),
        make_asset(path=r"C:\lib\claps\clap_01.wav", role="clap", pack="PackA"),
        make_asset(path=r"C:\lib\hats\hat_01.wav", role="hats", pack="PackA"),
        make_asset(
            path=r"C:\lib\fx\riser_whoosh.wav",
            role="fx",
            pack="PackA",
            name="riser_whoosh.wav",
        ),
        make_asset(
            path=r"C:\lib\leads\lead_stab.wav",
            role="lead",
            pack="PackA",
            name="lead_stab.wav",
        ),
        make_asset(
            path=r"C:\lib\bass\bass_loop_C.wav",
            role="bass",
            pack="PackA",
            name="bass_loop_C.wav",
        ),
    ]
    c.serum = [
        make_asset(
            path=r"C:\Xfer\Serum Presets\Presets\Bass\BA_stock.fxp",
            kind="serum",
            role="bass",
            ext=".fxp",
            pack="Bass",
            category="bass",
            origin="factory",
        ),
        make_asset(
            path=r"C:\Xfer\Serum Presets\Presets\Splice\BA_mine.fxp",
            kind="serum",
            role="bass",
            ext=".fxp",
            pack="Splice",
            category="bass",
            origin="splice",
        ),
        make_asset(
            path=r"C:\Xfer\Serum 2 Presets\Presets\Factory\Bass\BA_s2.SerumPreset",
            kind="serum",
            role="bass",
            ext=".serumpreset",
            pack="Factory",
            category="bass",
            origin="factory",
        ),
        make_asset(
            path=r"C:\Xfer\Serum 2 Presets\Presets\Splice\BA_s2_user.SerumPreset",
            kind="serum",
            role="bass",
            ext=".serumpreset",
            pack="Splice",
            category="bass",
            origin="splice",
        ),
        make_asset(
            path=r"C:\Xfer\Serum 2 Presets\Presets\User\BA_custom.SerumPreset",
            kind="serum",
            role="bass",
            ext=".serumpreset",
            pack="User",
            category="bass",
            origin="user",
        ),
    ]
    return c
