"""Random loop slot filler from in-memory catalog."""

from __future__ import annotations

import random
import re
from typing import Any

from .catalog import Asset, Catalog
from .scanner import is_factory_serum

# Transition / riser / build samples to optionally exclude.
# Use non-alnum boundaries so underscores match: Snare_Build_Overcast.wav
# (\b does NOT break on "_", so \bbuild\b misses pack-style names.)
_TOK = r"(?<![a-z0-9])(?:{inner})(?![a-z0-9])"
RISER_RE = re.compile(
    "|".join(
        [
            _TOK.format(
                inner=r"riser|rise|build(?:[-_]?ups?)?|builds?|"
                r"downlift(?:er)?s?|uplift(?:er)?s?|"
                r"drum[\s_-]?rolls?|snare[\s_-]?rolls?|tom[\s_-]?rolls?|"
                r"whoosh(?:es)?|sweeps?|fall(?:er)?s?|descends?"
            ),
            r"build[_-]?ups?|drumrolls?|snarerolls?",
        ]
    ),
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
    # Sample-based bass (Options: Bass audio) — not Serum
    "bass_audio": ["bass"],
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
    "bass_audio": "sample",
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
        "bass_audio",
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
    # Lead/bass (audio) stay sample-only — never fall back to Serum presets
    sample_only = slot in ("lead_audio", "bass_audio")
    if not pool and kind == "sample" and not sample_only:
        pool = collect("serum")
    if not pool and not sample_only:
        # Last resort: any asset matching role (serum + sample)
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


# Empty / explicit “no lean” → true random (no pack/path weighting).
_NO_STYLE_MARKERS = frozenset(
    {
        "",
        "none",
        "no preference",
        "nopreference",
        "any",
        "all",
        "random",
        "n/a",
        "na",
        "-",
        "—",
        "*",
    }
)

# Extra search terms for common genre labels (soft match only).
_STYLE_SYNONYMS: dict[str, tuple[str, ...]] = {
    "techno": ("techno", "tekno", "industrial"),
    "melodic": ("melodic",),
    "hard": ("hard", "hardgroove", "raw"),
    "house": ("house", "deep house", "bass house"),
    "tech": ("tech", "techhouse", "tech house"),
    "trance": ("trance", "uplifting", "psytrance"),
    "peak": ("peak", "peaktime", "peak time"),
    "acid": ("acid", "303", "tb303"),
    "minimal": ("minimal", "mintech"),
    "dub": ("dub", "dubtechno", "dub techno"),
    "ambient": ("ambient", "downtempo", "atmospheric"),
    "drum": ("drum", "dnb", "drum and bass", "jungle"),
    "bass": ("bass music", "uk bass", "halftime"),
    "break": ("break", "breaks", "breakbeat"),
    "garage": ("garage", "ukg", "2step", "2-step"),
    "trap": ("trap", "hybrid trap"),
    "hip": ("hip hop", "hiphop", "boom bap"),
    "hop": ("hip hop", "hiphop"),
    "idm": ("idm", "glitch", "experimental"),
    "industrial": ("industrial", "ebm"),
    "electro": ("electro", "electroclash"),
    "progressive": ("progressive", "prog"),
    "organic": ("organic", "live"),
    "cinematic": ("cinematic", "trailer", "orchestral"),
}

# Genres we can surface from pack/path text (specific phrases before broad ones in list
# only for readability; each label is scored independently).
_CATALOG_STYLE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Melodic Techno", re.compile(r"melodic[\s_-]*techno", re.I)),
    ("Hard Techno", re.compile(r"hard[\s_-]*techno|hardgroove|hard[\s_-]*groove", re.I)),
    ("Dub Techno", re.compile(r"dub[\s_-]*techno", re.I)),
    ("Tech House", re.compile(r"tech[\s_-]*house", re.I)),
    ("Melodic House", re.compile(r"melodic[\s_-]*house", re.I)),
    ("Afro House", re.compile(r"afro[\s_-]*house", re.I)),
    ("Deep House", re.compile(r"deep[\s_-]*house", re.I)),
    ("Bass House", re.compile(r"bass[\s_-]*house", re.I)),
    ("Peak Time", re.compile(r"peak[\s_-]*time", re.I)),
    ("Hard Dance", re.compile(r"hard[\s_-]*dance", re.I)),
    ("Drum & Bass", re.compile(r"drum[\s_-]*(?:and|&)[\s_-]*bass|\bdnb\b|\bd&b\b|\bjungle\b", re.I)),
    ("Hip Hop", re.compile(r"hip[\s_-]*hop|boom[\s_-]*bap", re.I)),
    ("Progressive", re.compile(r"progressive|prog[\s_-]*house|prog[\s_-]*techno", re.I)),
    ("Eurodance", re.compile(r"eurodance|euro[\s_-]*dance", re.I)),
    ("Techno", re.compile(r"techno|tekno", re.I)),
    ("Trance", re.compile(r"\btrance\b|psytrance|uplifting", re.I)),
    ("House", re.compile(r"\bhouse\b", re.I)),
    ("Phonk", re.compile(r"\bphonk\b", re.I)),
    ("Ambient", re.compile(r"ambient|downtempo|atmospheric", re.I)),
    ("Cinematic", re.compile(r"cinematic|trailer", re.I)),
    ("Acid", re.compile(r"\bacid\b|tb[\s_-]?303|\b303\b", re.I)),
    ("Minimal", re.compile(r"minimal|mintech", re.I)),
    ("Industrial", re.compile(r"industrial|\bebm\b", re.I)),
    ("Electro", re.compile(r"\belectro\b", re.I)),
    ("Garage", re.compile(r"\bgarage\b|\bukg\b|2[\s_-]*step", re.I)),
    ("Trap", re.compile(r"\btrap\b", re.I)),
    ("Breakbeat", re.compile(r"breakbeat|\bbreaks\b", re.I)),
    ("IDM", re.compile(r"\bidm\b|glitch", re.I)),
    ("Organic", re.compile(r"\borganic\b", re.I)),
    ("Dub", re.compile(r"\bdub\b", re.I)),
]


def catalog_style_suggestions(
    catalog: Catalog,
    *,
    limit: int = 10,
    min_packs: int = 1,
    min_assets: int = 2,
) -> list[dict[str, Any]]:
    """
    Rank genre labels by how often they appear in *this* library's pack names.

    Uses sample packs only (Serum folders are instrument categories, not genres).
    Returns up to `limit` items: {label, packs, assets}. Never invents styles
    that have no pack hits — empty catalog → [].
    """
    from collections import Counter

    pack_assets: Counter[str] = Counter()
    pack_blob: dict[str, str] = {}
    for a in catalog.samples:
        pack = (a.pack or "").strip()
        if not pack:
            continue
        pack_assets[pack] += 1
        if pack not in pack_blob:
            # Pack name dominates; path helps catch folder tags
            pack_blob[pack] = f"{pack} {(a.parent or '')} {(a.path or '')}".lower()

    asset_hits: Counter[str] = Counter()
    pack_hits: Counter[str] = Counter()
    for pack, n in pack_assets.items():
        blob = pack_blob.get(pack, pack.lower())
        for label, pat in _CATALOG_STYLE_PATTERNS:
            if pat.search(pack) or pat.search(blob):
                asset_hits[label] += n
                pack_hits[label] += 1

    ranked = sorted(
        asset_hits.items(),
        key=lambda kv: (-kv[1], -pack_hits[kv[0]], kv[0].lower()),
    )
    out: list[dict[str, Any]] = []
    for label, assets in ranked:
        packs = pack_hits[label]
        if packs < min_packs or assets < min_assets:
            continue
        out.append({"label": label, "packs": packs, "assets": assets})
        if len(out) >= max(1, min(limit, 10)):
            break
    return out


# Milder lean on drums/FX so cross-genre kits stay common.
_STYLE_ROLE_STRENGTH: dict[str, float] = {
    "kick": 0.35,
    "clap": 0.35,
    "snare": 0.35,
    "hats": 0.4,
    "perc": 0.4,
    "fx": 0.45,
    "loop": 0.55,
    "vocal": 0.75,
    "lead_audio": 0.85,
    "bass_audio": 0.9,
    "bass": 1.0,
    "lead": 1.0,
    "pad": 1.0,
    "pads": 1.0,
    "brass": 0.9,
    "chorus": 0.85,
    "guitar": 0.9,
    "keys": 0.9,
    "strings": 0.9,
}


def style_tokens(style: str | None) -> list[str]:
    """
    Tokenize free-text style into match terms.
    Empty / no-preference markers → [] (true random picks).
    """
    raw = (style or "").strip().lower()
    if raw in _NO_STYLE_MARKERS:
        return []
    # Split on common separators; keep multi-word phrases as well as parts
    parts = [p for p in re.split(r"[\s,/|+&]+", raw) if p and p not in _NO_STYLE_MARKERS]
    if not parts and raw not in _NO_STYLE_MARKERS:
        parts = [raw]
    tokens: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        t = term.strip().lower()
        if len(t) < 2 or t in seen or t in _NO_STYLE_MARKERS:
            return
        seen.add(t)
        tokens.append(t)

    # Full phrase first (e.g. "melodic techno", "tech house")
    if " " in raw or "-" in raw:
        add(raw.replace("-", " "))
        add(raw.replace(" ", "").replace("-", ""))

    for p in parts:
        add(p)
        add(p.replace("-", ""))
        for syn in _STYLE_SYNONYMS.get(p, ()):
            add(syn)
        # Multi-word synonym heads (first word of compound keys handled above)
        for key, syns in _STYLE_SYNONYMS.items():
            if key in p or p in key:
                for syn in syns:
                    add(syn)

    return tokens


def _token_in_blob(token: str, blob: str) -> bool:
    """Match token with soft boundaries (underscores, hyphens, path seps)."""
    if not token or not blob:
        return False
    # Prefer whole-token match so "tech" does not hit "technology" mid-word oddly;
    # still allow pack-style underscore boundaries.
    if len(token) <= 2:
        return bool(
            re.search(
                rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])",
                blob,
                re.I,
            )
        )
    if token in blob:
        return True
    return bool(
        re.search(
            rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])",
            blob,
            re.I,
        )
    )


def style_affinity(asset: Asset, tokens: list[str]) -> float:
    """
    Soft 0..1 affinity from pack / path / name hits.
    0 = no match (still eligible); higher = more style-aligned.
    """
    if not tokens:
        return 0.0
    pack = (asset.pack or "").lower()
    name = (asset.name or "").lower()
    path = (asset.path or "").lower().replace("\\", "/")
    parent = (asset.parent or "").lower()
    category = (asset.category or "").lower()
    role = (asset.role or "").lower()
    score = 0.0
    for tok in tokens:
        if _token_in_blob(tok, pack):
            score += 4.0
        if _token_in_blob(tok, path) or _token_in_blob(tok, parent):
            score += 2.5
        if _token_in_blob(tok, name):
            score += 2.0
        if category and _token_in_blob(tok, category):
            score += 1.0
        if role and _token_in_blob(tok, role):
            score += 0.5
    # Cap so a few strong hits dominate without extreme weight skew
    return min(1.0, score / 8.0)


def style_weight(asset: Asset, tokens: list[str], slot: str) -> float:
    """
    Sampling weight. Floor 1.0 so non-matching assets stay in the pool.
    """
    if not tokens:
        return 1.0
    strength = _STYLE_ROLE_STRENGTH.get(slot, 0.8)
    # Base boost scale: drums stay mild; melodic slots lean harder
    boost = 6.0 * strength * style_affinity(asset, tokens)
    return 1.0 + boost


def pick_from_pool(pool: list[Asset], *, style: str | None = None, slot: str = "") -> Asset:
    """Uniform random when style is empty; weighted otherwise. Never filters out."""
    if len(pool) == 1:
        return pool[0]
    tokens = style_tokens(style)
    if not tokens:
        return random.choice(pool)
    weights = [style_weight(a, tokens, slot) for a in pool]
    return random.choices(pool, weights=weights, k=1)[0]


def pick_asset(
    catalog: Catalog,
    slot: str,
    exclude_path: str | None = None,
    serum_engine: str = "both",
    serum_type: str = "any",
    filter_risers: bool = False,
    filter_factory_serum: bool = False,
    style: str | None = None,
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
    return pick_from_pool(pool, style=style, slot=slot)


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
            style=style,
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
    Each track: {id, type, locked?, preset_locked?, path?, serum_engine?, serum_type?, ...}
    `locked` keeps the whole track (sound + MIDI on the client).
    `preset_locked` keeps the sound/preset only so MIDI can still change.
    Returns slots keyed by track id.
    """
    slots_out: dict[str, Any] = {}
    for t in tracks:
        tid = str(t.get("id") or t.get("type") or "")
        ttype = str(t.get("type") or tid.split("__")[0] or "synth")
        if not tid:
            continue
        keep_sound = bool(
            t.get("locked") or t.get("preset_locked") or t.get("presetLocked")
        ) and t.get("path")
        if keep_sound:
            slots_out[tid] = {
                "role": ttype,
                "id": tid,
                "locked": bool(t.get("locked")),
                "preset_locked": bool(t.get("preset_locked")),
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
            style=style,
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
    style: str | None = None,
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
        style=style,
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
