"""Random loop slot filler from in-memory catalog."""

from __future__ import annotations

import random
import re
from typing import Any

from .catalog import Asset, Catalog
from .scanner import is_factory_serum

# Transition / riser-style samples to optionally exclude
RISER_RE = re.compile(
    r"\briser\b|\brise\b|\bbuild(?:[-_]?up)?\b|\bdownlift(?:er)?\b|\buplift(?:er)?\b|"
    r"\bdrum[\s_-]?roll\b|\bsnare[\s_-]?roll\b|\btom[\s_-]?roll\b|"
    r"\bwhoosh\b|\bsweep\b|\bfall(?:er)?\b|\bdescend\b|"
    r"\briser|downlifter|uplifter|buildup|build_up|drumroll|snareroll",
    re.I,
)


def is_riser_like(asset: Asset) -> bool:
    blob = f"{asset.name} {asset.path} {asset.pack}".lower().replace("\\", "/")
    return bool(RISER_RE.search(blob))

# UI slot → preferred roles (first match with assets wins)
SLOT_ROLES: dict[str, list[str]] = {
    "kick": ["kick"],
    "clap": ["clap", "snare"],
    "hats": ["hats"],
    "perc": ["perc"],
    "bass": ["bass"],
    "lead": ["lead", "synth", "pad"],
    # Sample-based lead (Options: Lead audio) — not Serum
    "lead_audio": ["lead", "synth", "pad", "loop"],
    "fx": ["fx"],
    "vocal": ["vocal"],
    "brass": ["brass", "synth"],
    "chorus": ["chord", "pad", "synth", "vocal"],
    "pad": ["pad"],
    "pads": ["pad"],
    "guitar": ["guitar", "pluck", "synth"],
    "keys": ["keys", "piano", "organ", "synth"],
    "strings": ["pad", "synth"],
}

# Prefer samples for drums; serum for musical
SLOT_KIND: dict[str, str | None] = {
    "kick": "sample",
    "clap": "sample",
    "hats": "sample",
    "perc": "sample",
    "snare": "sample",
    "bass": "serum",
    "lead": "serum",
    "lead_audio": "sample",
    "fx": "sample",
    "vocal": "sample",
    "brass": "serum",
    "chorus": "serum",
    "pad": "serum",
    "pads": "serum",
    "guitar": "serum",
    "keys": "serum",
    "strings": "serum",
}

SAMPLE_SLOT_TYPES = frozenset(
    {
        "kick",
        "clap",
        "hats",
        "perc",
        "fx",
        "snare",
        "vocal",
        "loop",
        "lead_audio",
    }
)


def get_slot_kind(slot: str) -> str | None:
    if slot in SLOT_KIND:
        return SLOT_KIND[slot]
    if slot in SAMPLE_SLOT_TYPES:
        return "sample"
    # Musical / Serum browser types (arp, pad, pluck, …)
    return "serum"


def _pool_for_slot(
    catalog: Catalog,
    slot: str,
    *,
    serum_type: str = "any",
) -> list[Asset]:
    roles = SLOT_ROLES.get(slot, [slot])
    kind = get_slot_kind(slot)

    def collect(k: str | None) -> list[Asset]:
        out: list[Asset] = []
        for role in roles:
            out.extend(catalog.by_role(role, kind=k))
        return out

    # Serum tracks with an explicit type: draw from all serum of that category
    st = (serum_type or "any").lower().strip()
    # Aliases for Options instrument names → catalog categories / path tokens
    st_aliases = {
        "pads": ["pad"],
        "strings": ["pad", "string", "orchestral"],
        "chorus": ["chord", "pad", "vox", "vocal"],
        "keys": ["keys", "piano", "organ", "keyboard", "e piano"],
        "brass": ["brass"],
        "guitar": ["guitar", "pluck"],
    }
    if kind == "serum" and st not in ("any", "*", "all", ""):
        tokens = st_aliases.get(st, [st])
        pool = [
            a
            for a in catalog.serum
            if (a.category or a.role or "").lower() in tokens
            or any(
                f"/{t}/" in a.path.lower().replace("\\", "/")
                or f"/{t} " in a.path.lower().replace("\\", "/")
                or f"\\{t}\\" in a.path.lower()
                for t in tokens
            )
        ]
        if pool:
            return pool

    pool = collect(kind)
    if not pool and kind == "serum":
        # Fall back to samples for that role
        pool = collect("sample")
    # Lead (audio) stays sample-only — never fall back to Serum presets
    if not pool and kind == "sample" and slot not in ("lead_audio",):
        pool = collect("serum")
    if not pool:
        # Last resort: any sample matching role names in path
        pool = collect(None)
    # Prefer one-shots over loops for drum slots
    if slot in ("kick", "clap", "perc") and pool:
        oneshots = [a for a in pool if a.role != "loop" and "loop" not in a.name.lower()]
        if oneshots:
            pool = oneshots
    return pool


def _filter_serum_engine(pool: list[Asset], serum_engine: str) -> list[Asset]:
    """serum_engine: s1 | s2 | both | none (default both)."""
    eng = (serum_engine or "both").lower().strip()
    if eng in ("none", "off", "0", "disabled"):
        return []
    if eng in ("s1", "serum1", "1"):
        return [a for a in pool if a.ext.lower() == ".fxp"]
    if eng in ("s2", "serum2", "2"):
        return [a for a in pool if a.ext.lower() == ".serumpreset"]
    return pool


def pick_asset(
    catalog: Catalog,
    slot: str,
    exclude_path: str | None = None,
    serum_engine: str = "both",
    serum_type: str = "any",
    filter_risers: bool = False,
    filter_factory_serum: bool = False,
) -> Asset | None:
    pool = _pool_for_slot(catalog, slot, serum_type=serum_type)
    if not pool:
        return None
    if exclude_path:
        filtered = [a for a in pool if a.path != exclude_path]
        if filtered:
            pool = filtered
    if filter_risers:
        # Strict: never fall back to risers when the filter is on
        pool = [a for a in pool if not is_riser_like(a)]
    # Serum slots: honor Options Serum 1 / 2 checkboxes (strict — no fallback)
    if get_slot_kind(slot) == "serum":
        eng = (serum_engine or "both").lower().strip()
        if eng in ("none", "off", "0", "disabled"):
            return None
        if eng in ("s1", "serum1", "1", "s2", "serum2", "2"):
            pool = _filter_serum_engine(pool, eng)
        else:
            # Both: slight preference for Serum 2 when available
            s2 = [a for a in pool if a.ext.lower() == ".serumpreset"]
            s1 = [a for a in pool if a.ext.lower() == ".fxp"]
            if s2 and s1 and random.random() < 0.6:
                pool = s2
        # Splice/User only — drop stock Factory / S1 category banks
        if filter_factory_serum:
            kept = [a for a in pool if not is_factory_serum(a)]
            pool = kept  # strict: empty → no match (no factory fallback)
    if not pool:
        return None
    return random.choice(pool)


def _asset_to_slot_dict(slot: str, asset: Asset, *, locked: bool = False) -> dict[str, Any]:
    meta = f"{asset.pack} · {asset.kind}" if asset.pack else asset.kind
    if asset.kind == "serum":
        eng = "Serum 2" if asset.ext.lower() == ".serumpreset" else "Serum 1"
        meta = f"{eng} · {asset.pack} · preset"
        display = f"{eng} · {asset.pack} / {asset.name}"
    else:
        display = asset.name
    return {
        "role": slot,
        "locked": locked,
        "empty": False,
        "path": asset.path,
        "name": display,
        "kind": asset.kind,
        "pack": asset.pack,
        "meta": meta,
        "ext": asset.ext,
    }


def generate_loop(
    catalog: Catalog,
    locked: dict[str, dict[str, Any]] | None = None,
    bpm: int = 140,
    key: str = "F minor",
    style: str = "Techno",
    include_fx: bool = True,
    serum_engines: dict[str, str] | None = None,
    serum_types: dict[str, str] | None = None,
    filter_risers: bool = False,
    filter_factory_serum: bool = False,
) -> dict[str, Any]:
    """Return a loop dict with slots. Locked slots keep previous asset."""
    locked = locked or {}
    serum_engines = serum_engines or {}
    serum_types = serum_types or {}
    slots_out: dict[str, Any] = {}
    slot_names = ["kick", "clap", "hats", "perc", "bass", "lead"]
    if include_fx:
        slot_names.append("fx")

    for slot in slot_names:
        if slot in locked and locked[slot].get("path"):
            slots_out[slot] = {
                "role": slot,
                "locked": True,
                "empty": False,
                **{k: locked[slot][k] for k in ("path", "name", "kind", "pack", "meta") if k in locked[slot]},
            }
            # normalize fields
            slots_out[slot].setdefault("name", locked[slot].get("name", ""))
            slots_out[slot].setdefault("kind", locked[slot].get("kind", "sample"))
            slots_out[slot].setdefault("pack", locked[slot].get("pack", ""))
            slots_out[slot].setdefault(
                "meta",
                f"{slots_out[slot].get('pack', '')} · {slots_out[slot].get('kind', '')}".strip(" ·"),
            )
            continue

        # Sparse FX sometimes
        if slot == "fx" and random.random() < 0.45:
            slots_out[slot] = {
                "role": slot,
                "locked": False,
                "empty": True,
                "path": None,
                "name": "— empty —",
                "kind": None,
                "pack": "",
                "meta": "optional · sparse ok",
            }
            continue

        eng = serum_engines.get(slot, "both")
        stype = serum_types.get(slot) or (
            "bass" if slot == "bass" else "lead" if slot == "lead" else "any"
        )
        if get_slot_kind(slot) == "serum" and stype in ("any", "", None):
            stype = slot if slot not in SAMPLE_SLOT_TYPES else "any"
        asset = pick_asset(
            catalog,
            slot,
            serum_engine=eng,
            serum_type=stype,
            filter_risers=filter_risers,
            filter_factory_serum=filter_factory_serum,
        )
        if asset is None:
            slots_out[slot] = {
                "role": slot,
                "locked": False,
                "empty": True,
                "path": None,
                "name": "— no match —",
                "kind": None,
                "pack": "",
                "meta": f"no {slot} assets in catalog — rescan or add samples",
            }
            continue

        slots_out[slot] = _asset_to_slot_dict(slot, asset, locked=False)

    return {
        "bpm": bpm,
        "key": key,
        "style": style,
        "slots": slots_out,
    }


def generate_tracks(
    catalog: Catalog,
    tracks: list[dict[str, Any]],
    *,
    bpm: int = 140,
    key: str = "F minor",
    style: str = "Techno",
    filter_risers: bool = False,
    filter_factory_serum: bool = False,
) -> dict[str, Any]:
    """
    Fill a dynamic track list.
    Each track: {id, type, locked?, path?, serum_engine?, serum_type?, ...}
    Returns slots keyed by track id.
    """
    slots_out: dict[str, Any] = {}
    for t in tracks:
        tid = str(t.get("id") or t.get("type") or "")
        ttype = str(t.get("type") or tid.split("__")[0] or "synth")
        if not tid:
            continue
        if t.get("locked") and t.get("path"):
            slots_out[tid] = {
                "role": ttype,
                "id": tid,
                "locked": True,
                "empty": False,
                "path": t.get("path"),
                "name": t.get("name") or "",
                "kind": t.get("kind"),
                "pack": t.get("pack") or "",
                "meta": t.get("meta") or "",
                "ext": t.get("ext"),
            }
            continue
        eng = t.get("serum_engine") or "both"
        stype = t.get("serum_type") or (
            ttype if get_slot_kind(ttype) == "serum" else "any"
        )
        asset = pick_asset(
            catalog,
            ttype,
            serum_engine=eng,
            serum_type=stype,
            filter_risers=filter_risers,
            filter_factory_serum=filter_factory_serum,
        )
        if asset is None:
            slots_out[tid] = {
                "role": ttype,
                "id": tid,
                "locked": False,
                "empty": True,
                "path": None,
                "name": "— no match —",
                "kind": None,
                "pack": "",
                "meta": f"no {ttype} assets in catalog",
            }
            continue
        d = _asset_to_slot_dict(ttype, asset, locked=False)
        d["id"] = tid
        slots_out[tid] = d
    return {"bpm": bpm, "key": key, "style": style, "slots": slots_out}


def reroll_slot(
    catalog: Catalog,
    slot: str,
    current_path: str | None = None,
    serum_engine: str = "both",
    serum_type: str = "any",
    filter_risers: bool = False,
    filter_factory_serum: bool = False,
) -> dict[str, Any]:
    if slot == "fx" and random.random() < 0.25:
        return {
            "role": slot,
            "locked": False,
            "empty": True,
            "path": None,
            "name": "— empty —",
            "kind": None,
            "pack": "",
            "meta": "optional · sparse ok",
        }
    if get_slot_kind(slot) == "serum" and (not serum_type or serum_type == "any"):
        serum_type = slot
    asset = pick_asset(
        catalog,
        slot,
        exclude_path=current_path,
        serum_engine=serum_engine,
        serum_type=serum_type,
        filter_risers=filter_risers,
        filter_factory_serum=filter_factory_serum,
    )
    if asset is None:
        return {
            "role": slot,
            "locked": False,
            "empty": True,
            "path": None,
            "name": "— no match —",
            "kind": None,
            "pack": "",
            "meta": f"no {slot} assets in catalog",
        }
    return _asset_to_slot_dict(slot, asset, locked=False)
