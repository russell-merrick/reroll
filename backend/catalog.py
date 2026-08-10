"""In-memory library catalog (no database)."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Asset:
    path: str
    name: str
    kind: str  # sample | serum
    role: str  # kick, clap, snare, hats, perc, bass, lead, pad, fx, vocal, loop, synth, unknown
    ext: str
    pack: str = ""
    parent: str = ""
    # Serum browser category (folder): bass, lead, arp, pad, … empty for samples
    category: str = ""
    # Serum origin: factory | splice | user | other (empty for samples)
    origin: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Catalog:
    samples: list[Asset] = field(default_factory=list)
    serum: list[Asset] = field(default_factory=list)
    sample_roots: list[str] = field(default_factory=list)
    serum_roots: list[str] = field(default_factory=list)
    scanned: bool = False
    last_error: str | None = None

    def by_role(self, role: str, kind: str | None = None) -> list[Asset]:
        role = role.lower()
        pool = self.samples if kind != "serum" else self.serum
        if kind is None:
            pool = self.samples + self.serum
        if kind == "sample":
            pool = self.samples
        return [a for a in pool if a.role == role]

    def role_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for a in self.samples + self.serum:
            counts[a.role] = counts.get(a.role, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: (-x[1], x[0])))

    def serum_categories(self) -> list[str]:
        """Sorted category ids present in the serum catalog (for UI filter)."""
        cats = {a.category for a in self.serum if a.category}
        return sorted(cats)

    def summary(self) -> dict[str, Any]:
        packs = {a.pack for a in self.samples if a.pack}
        serum1 = sum(1 for a in self.serum if a.ext.lower() == ".fxp")
        serum2 = sum(1 for a in self.serum if a.ext.lower() == ".serumpreset")
        serum_factory = sum(1 for a in self.serum if (a.origin or "").lower() == "factory")
        serum_splice = sum(1 for a in self.serum if (a.origin or "").lower() == "splice")
        serum_user = sum(1 for a in self.serum if (a.origin or "").lower() == "user")
        return {
            "scanned": self.scanned,
            "sample_count": len(self.samples),
            "serum_count": len(self.serum),
            "serum1_count": serum1,
            "serum2_count": serum2,
            "serum_factory_count": serum_factory,
            "serum_splice_count": serum_splice,
            "serum_user_count": serum_user,
            "pack_count": len(packs),
            "sample_roots": self.sample_roots,
            "serum_roots": self.serum_roots,
            "role_counts": self.role_counts(),
            "serum_categories": self.serum_categories(),
            "last_error": self.last_error,
        }


# Process-wide catalog
CATALOG = Catalog()
