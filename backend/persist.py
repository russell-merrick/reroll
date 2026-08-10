"""SQLite persistence for the library catalog (scan once, load fast)."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .catalog import Asset, Catalog

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
  path TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  role TEXT NOT NULL,
  ext TEXT NOT NULL,
  pack TEXT NOT NULL DEFAULT '',
  parent TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT '',
  origin TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_assets_kind ON assets(kind);
CREATE INDEX IF NOT EXISTS idx_assets_role ON assets(role);
"""


def default_db_path(root: Path) -> Path:
    return root / "library.db"


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def save_catalog(catalog: Catalog, db_path: Path) -> dict[str, Any]:
    """Replace DB contents with the current in-memory catalog."""
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM assets")
        conn.execute("DELETE FROM meta")
        rows = []
        for a in catalog.samples + catalog.serum:
            rows.append(
                (
                    a.path,
                    a.name,
                    a.kind,
                    a.role,
                    a.ext,
                    a.pack or "",
                    a.parent or "",
                    a.category or "",
                    a.origin or "",
                )
            )
        conn.executemany(
            """
            INSERT OR REPLACE INTO assets
              (path, name, kind, role, ext, pack, parent, category, origin)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        meta = {
            "scanned_at": str(time.time()),
            "sample_roots": json.dumps(list(catalog.sample_roots)),
            "serum_roots": json.dumps(list(catalog.serum_roots)),
            "sample_count": str(len(catalog.samples)),
            "serum_count": str(len(catalog.serum)),
        }
        for k, v in meta.items():
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (k, v)
            )
        conn.commit()
        return {
            "ok": True,
            "path": str(db_path.resolve()),
            "assets": len(rows),
        }
    finally:
        conn.close()


def load_catalog(db_path: Path) -> Catalog | None:
    """Load catalog from SQLite, or None if missing/empty/corrupt."""
    if not db_path.is_file():
        return None
    try:
        conn = _connect(db_path)
    except sqlite3.Error:
        return None
    try:
        n = conn.execute("SELECT COUNT(*) AS c FROM assets").fetchone()["c"]
        if not n:
            return None
        cat = Catalog()
        for row in conn.execute("SELECT * FROM assets"):
            asset = Asset(
                path=row["path"],
                name=row["name"],
                kind=row["kind"],
                role=row["role"],
                ext=row["ext"],
                pack=row["pack"] or "",
                parent=row["parent"] or "",
                category=row["category"] or "",
                origin=row["origin"] or "",
            )
            if asset.kind == "serum":
                cat.serum.append(asset)
            else:
                cat.samples.append(asset)
        meta = {
            r["key"]: r["value"]
            for r in conn.execute("SELECT key, value FROM meta")
        }
        try:
            cat.sample_roots = json.loads(meta.get("sample_roots") or "[]")
        except json.JSONDecodeError:
            cat.sample_roots = []
        try:
            cat.serum_roots = json.loads(meta.get("serum_roots") or "[]")
        except json.JSONDecodeError:
            cat.serum_roots = []
        cat.scanned = True
        cat.last_error = None
        return cat
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def catalog_stats(db_path: Path) -> dict[str, Any]:
    if not db_path.is_file():
        return {"exists": False}
    try:
        conn = _connect(db_path)
        n = conn.execute("SELECT COUNT(*) AS c FROM assets").fetchone()["c"]
        meta = {
            r["key"]: r["value"]
            for r in conn.execute("SELECT key, value FROM meta")
        }
        conn.close()
        return {
            "exists": True,
            "path": str(db_path.resolve()),
            "assets": n,
            "scanned_at": meta.get("scanned_at"),
            "sample_count": meta.get("sample_count"),
            "serum_count": meta.get("serum_count"),
        }
    except sqlite3.Error as exc:
        return {"exists": True, "error": str(exc)}
