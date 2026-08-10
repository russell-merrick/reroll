"""
Optional live Serum sync test (needs py3.12 + DawDreamer + Serum).

  pytest -m serum
  # or:
  py -3.12 host/test_serum_sync.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "host" / "test_serum_sync.py"


def _has_serum_preset() -> bool:
    home = Path.home()
    for folder in (
        home / "Documents/Xfer/Serum 2 Presets/Presets",
        home / "Documents/Xfer/Serum Presets/Presets",
    ):
        if not folder.is_dir():
            continue
        if any(folder.rglob("*.SerumPreset")) or any(folder.rglob("*.fxp")):
            return True
    return False


@pytest.mark.serum
def test_serum_kick_grid_sync():
    if not SCRIPT.is_file():
        pytest.skip("host/test_serum_sync.py missing")
    if not _has_serum_preset():
        pytest.skip("no local Serum presets")

    # Prefer 3.12 for DawDreamer
    candidates = [
        [sys.executable],
        ["py", "-3.12"],
    ]
    # On Windows, sys.executable may be 3.14 — try py -3.12 first for this test
    if os.name == "nt":
        candidates = [["py", "-3.12"], [sys.executable]]

    last_err = None
    for cmd_prefix in candidates:
        try:
            proc = subprocess.run(
                [*cmd_prefix, str(SCRIPT)],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        except FileNotFoundError as exc:
            last_err = exc
            continue
        out = (proc.stdout or "") + (proc.stderr or "")
        if "SKIP:" in out:
            pytest.skip(out.strip().splitlines()[-1])
        if "PASS:" in out or proc.returncode == 0:
            assert "PASS:" in out or proc.returncode == 0
            return
        last_err = RuntimeError(f"exit {proc.returncode}\n{out}")

    if last_err:
        pytest.fail(str(last_err))
