"""Filesystem scanners for samples and Serum presets."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .catalog import Asset, Catalog

AUDIO_EXTS = {".wav", ".aif", ".aiff", ".flac"}
# Serum 1 factory/user .fxp · Serum 2 .SerumPreset
SERUM_EXTS = {".fxp", ".serumpreset"}

# role -> patterns matched against "path + name" (lowercase)
# Note: pack dumps often use `_Bass_` / `_BA_` — `_` is a word char, so avoid bare `\bbass`.
ROLE_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("kick", re.compile(r"\bkick|\bbd\b|bassdrum|bass_drum")),
    ("clap", re.compile(r"\bclap")),
    ("snare", re.compile(r"\bsnare|\bsd\b")),
    ("hats", re.compile(r"\bhi[-_]?hat|\bhats?\b|\bhh\b|\bclosed[-_]?hat|\bopen[-_]?hat|\bcymbal|\bride\b")),
    ("perc", re.compile(r"\bperc|\btom\b|\brim\b|\bshaker|\bconga|\bbongo|\bclave|\bcowbell|\bdrum")),
    ("bass", re.compile(r"bass|\bsub\b|\b808\b|(?:^|[^a-z0-9])ba[_-]")),
    ("lead", re.compile(r"lead|\bacid\b|\bstab\b|(?:^|[^a-z0-9])ld[_-]")),
    ("pad", re.compile(r"(?:^|[^a-z0-9])pad(?:[^a-z0-9]|$)|atmos|\bdrone\b|(?:^|[^a-z0-9])pd[_-]")),
    ("vocal", re.compile(r"vocal|\bvox\b|\bvoice|\bchoir")),
    ("fx", re.compile(r"(?:^|[^a-z0-9])fx(?:[^a-z0-9]|$)|riser|impact|sweep|noise|whoosh|transition")),
    ("loop", re.compile(r"loop")),
    ("synth", re.compile(r"synth|pluck|\bkeys?\b|chord|\barp\b|(?:^|[^a-z0-9])ar[_-]")),
]

# Serum parent-folder → role (Serum 1 + Serum 2 Factory category names)
# Keep category key (= folder) for UI type filter; role is for coarse pooling.
SERUM_FOLDER_ROLE = {
    "bass": "bass",
    "bass (hard)": "bass",
    "leads": "lead",
    "lead": "lead",
    "pads": "pad",
    "pad": "pad",
    "plucked": "pluck",
    "pluck": "pluck",
    "seq": "seq",
    "synth": "synth",
    "fx": "fx",
    "sfx": "fx",
    "misc": "synth",
    "splice": "synth",
    "user": "synth",
    "arp": "arp",
    "bell": "bell",
    "brass": "brass",
    "chord": "chord",
    "drum": "perc",
    "drumkit": "perc",
    "e piano": "keys",
    "guitar": "guitar",
    "hit": "fx",
    "hoover": "hoover",
    "instrument": "synth",
    "keyboard": "keys",
    "loop": "loop",
    "mallet": "mallet",
    "orchestral": "pad",
    "organ": "organ",
    "piano": "piano",
    "soundscape": "pad",
    "string": "pad",
    "keys": "keys",
    "template": "synth",
    "vox": "vocal",
    "woodwind": "synth",
}

# UI filter options (value = category key stored on assets)
SERUM_TYPE_OPTIONS = [
    "any",
    "bass",
    "lead",
    "arp",
    "pad",
    "pluck",
    "seq",
    "synth",
    "keys",
    "piano",
    "organ",
    "hoover",
    "bell",
    "chord",
    "guitar",
    "mallet",
    "loop",
    "fx",
    "vocal",
]

DEFAULT_SAMPLE_ROOTS = [
    Path(os.path.expandvars(r"%USERPROFILE%\Documents\Splice\Samples\packs")),
]
DEFAULT_SERUM_ROOTS = [
    # Serum 1
    Path(os.path.expandvars(r"%USERPROFILE%\Documents\Xfer\Serum Presets\Presets")),
    # Serum 2
    Path(os.path.expandvars(r"%USERPROFILE%\Documents\Xfer\Serum 2 Presets\Presets")),
]


def _norm_root(path: Path | str) -> Path | None:
    """Expand and resolve a root; return None if empty."""
    s = str(path or "").strip()
    if not s:
        return None
    try:
        return Path(s).expanduser().resolve()
    except OSError:
        try:
            return Path(s).expanduser()
        except OSError:
            return None


def merge_scan_roots(
    extras: list[str] | list[Path] | None,
    defaults: list[Path],
) -> list[Path]:
    """Defaults first, then extra roots (deduped by resolved path)."""
    out: list[Path] = []
    seen: set[str] = set()
    for raw in list(defaults) + list(extras or []):
        p = _norm_root(raw)
        if p is None:
            continue
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def classify_sample(path: Path, root: Path) -> str:
    blob = str(path).lower().replace("\\", "/")
    name = path.name.lower()
    # Prefer filename hits, then full path
    for role, pat in ROLE_RULES:
        if pat.search(name):
            return role
    for role, pat in ROLE_RULES:
        if pat.search(blob):
            return role
    return "unknown"


def _serum_folder_key(path: Path, root: Path) -> str | None:
    """Deepest known Serum category folder for this preset path."""
    try:
        rel = path.relative_to(root)
        parts = [p.lower() for p in rel.parts[:-1]]  # folders only
        for folder in reversed(parts):
            if folder in SERUM_FOLDER_ROLE:
                return folder
        if parts and parts[0] in SERUM_FOLDER_ROLE:
            return parts[0]
    except ValueError:
        pass
    return None


def serum_category(path: Path, root: Path) -> str:
    """Stable category id for UI filter (bass, arp, lead, …)."""
    key = _serum_folder_key(path, root)
    if not key:
        # Flat dumps (e.g. Google Drive folder): infer from filename
        role = classify_sample(path, root)
        return role if role not in ("", "unknown") else ""
    # Normalize aliases to the role/category we expose in the UI
    role = SERUM_FOLDER_ROLE.get(key, key)
    # Prefer friendly type names over coarse perc/pad collapses where useful
    if key in ("bass", "bass (hard)"):
        return "bass"
    if key in ("lead", "leads"):
        return "lead"
    if key in ("pad", "pads", "orchestral", "soundscape", "string"):
        return "pad"
    if key in ("sfx", "fx", "hit"):
        return "fx"
    if key in ("e piano", "keyboard", "keys"):
        return "keys"
    if key in ("drum", "drumkit"):
        return "perc"
    if key == "vox":
        return "vocal"
    return role if role in SERUM_TYPE_OPTIONS else key.replace(" ", "-")


def classify_serum(path: Path, root: Path) -> str:
    # Category is usually immediate child of Presets root
    # Serum 2: Presets/Factory/Bass/... or Presets/User/...
    key = _serum_folder_key(path, root)
    if key and key in SERUM_FOLDER_ROLE:
        return SERUM_FOLDER_ROLE[key]
    return classify_sample(path, root)


def pack_name(path: Path, root: Path) -> str:
    try:
        rel = path.relative_to(root)
        # Nested: first folder under root; flat file: root folder name
        if len(rel.parts) >= 2:
            return rel.parts[0]
        return root.name
    except ValueError:
        pass
    return path.parent.name


# Serum 1 stock category folders under Documents/Xfer/Serum Presets/Presets
SERUM1_FACTORY_PACKS = frozenset(
    {
        "bass",
        "bass (hard)",
        "fx",
        "leads",
        "misc",
        "pads",
        "plucked",
        "seq",
        "synth",
        "templates",
        "template",
    }
)


def serum_origin(path: Path, root: Path) -> str:
    """
    Classify preset bank source for filter-out-factory.

    - factory: stock Xfer banks (S1 categories, S2 Factory, S1 Presets reimports)
    - splice: Splice downloads folder
    - user: User folder / other non-stock banks (incl. custom roots)
    """
    try:
        rel = path.relative_to(root)
        parts = [p.lower() for p in rel.parts[:-1]]
        pack = parts[0] if parts else ""
    except ValueError:
        pack = (path.parent.name or "").lower()
        parts = []

    blob = str(path).lower().replace("\\", "/")

    if pack == "splice" or "/splice/" in blob:
        return "splice"
    if pack == "user" or "/user/" in blob:
        return "user"
    # Serum 2 factory bank + converted stock S1 bank
    if pack == "factory" or "/factory/" in blob:
        return "factory"
    if pack in ("s1 presets", "s1 preset") or "/s1 presets/" in blob:
        return "factory"

    # Stock-folder heuristics only apply under Xfer's install trees
    under_xfer = "xfer" in blob or any(
        str(d).lower().replace("\\", "/") in blob
        for d in DEFAULT_SERUM_ROOTS
    )
    if under_xfer:
        # Serum 1: top-level category folders are factory
        if path.suffix.lower() == ".fxp" and pack in SERUM1_FACTORY_PACKS:
            return "factory"
        if path.suffix.lower() == ".fxp" and pack and pack not in ("splice", "user"):
            # Unknown top-level under S1 Presets — treat as factory-like stock
            return "factory"
    # Custom roots (Drive dumps, curated banks) → user so filter-factory keeps them
    return "user"


def is_factory_serum(asset: Asset) -> bool:
    """True for stock/default banks (filter target when Options is on)."""
    if asset.kind != "serum":
        return False
    origin = (asset.origin or "").lower()
    if origin in ("factory", "splice", "user"):
        return origin == "factory"
    # Fallback if unscanned/legacy asset without origin tag
    p = str(asset.path or "").lower().replace("\\", "/")
    pack = (asset.pack or "").lower()
    if pack == "splice" or "/splice/" in p:
        return False
    if pack == "user" or "/user/" in p:
        return False
    if pack == "factory" or "/factory/" in p:
        return True
    if "s1 presets" in pack or "/s1 presets/" in p:
        return True
    if pack in SERUM1_FACTORY_PACKS:
        return True
    # Serum 1 outside Splice/User is treated as stock
    if (asset.ext or "").lower() == ".fxp":
        return True
    return False


def scan_audio_root(root: Path) -> list[Asset]:
    assets: list[Asset] = []
    if not root.is_dir():
        return assets
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            ext = Path(fn).suffix.lower()
            if ext not in AUDIO_EXTS:
                continue
            p = Path(dirpath) / fn
            assets.append(
                Asset(
                    path=str(p),
                    name=fn,
                    kind="sample",
                    role=classify_sample(p, root),
                    ext=ext,
                    pack=pack_name(p, root),
                    parent=str(p.parent),
                )
            )
    return assets


def scan_serum_root(root: Path) -> list[Asset]:
    assets: list[Asset] = []
    if not root.is_dir():
        return assets
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            ext = Path(fn).suffix.lower()
            if ext not in SERUM_EXTS:
                continue
            p = Path(dirpath) / fn
            assets.append(
                Asset(
                    path=str(p),
                    name=fn,
                    kind="serum",
                    role=classify_serum(p, root),
                    ext=ext,
                    pack=pack_name(p, root),
                    parent=str(p.parent),
                    category=serum_category(p, root),
                    origin=serum_origin(p, root),
                )
            )
    return assets


def scan_library(
    catalog: Catalog,
    sample_roots: list[Path] | None = None,
    serum_roots: list[Path] | None = None,
    *,
    extra_sample_roots: list[str] | list[Path] | None = None,
    extra_serum_roots: list[str] | list[Path] | None = None,
) -> Catalog:
    """
    Walk sample + Serum roots into catalog.

    If sample_roots / serum_roots are omitted, use defaults plus optional extras
    (user-configured folders, e.g. Google Drive preset dumps).
    """
    if sample_roots is None:
        sample_roots = merge_scan_roots(extra_sample_roots, DEFAULT_SAMPLE_ROOTS)
    if serum_roots is None:
        serum_roots = merge_scan_roots(extra_serum_roots, DEFAULT_SERUM_ROOTS)
    catalog.samples = []
    catalog.serum = []
    catalog.sample_roots = []
    catalog.serum_roots = []
    catalog.last_error = None

    missing: list[str] = []
    for root in sample_roots:
        n = _norm_root(root)
        if n is None:
            continue
        catalog.sample_roots.append(str(n))
        if not n.is_dir():
            missing.append(str(n))
            continue
        catalog.samples.extend(scan_audio_root(n))

    for root in serum_roots:
        n = _norm_root(root)
        if n is None:
            continue
        catalog.serum_roots.append(str(n))
        if not n.is_dir():
            missing.append(str(n))
            continue
        catalog.serum.extend(scan_serum_root(n))

    catalog.scanned = True
    if missing:
        catalog.last_error = "Missing roots: " + "; ".join(missing)
    return catalog
