#!/usr/bin/env python3
"""Non-interactive smoke check for the local NES kickoff path.

Always requires a configured ROM under roms/ (or argv / MESEN_ROM).
Mesen is optional until the local download finishes: missing binary is a
WARN, not a FAIL, so scaffold CI can pass before the emulator is installed.
Does not launch Mesen (GUI probes are unreliable for CI-style checks).
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def configured_rom() -> str | None:
    if len(sys.argv) > 1:
        return sys.argv[1]
    if os.environ.get("MESEN_ROM"):
        return os.environ["MESEN_ROM"]
    games_file = REPO / "config" / "games.yaml"
    if games_file.exists():
        text = games_file.read_text(encoding="utf-8")
        match = re.search(r"^\s*rom:\s*[\"']?([^\"']+?)[\"']?\s*$", text, re.MULTILINE)
        if match:
            return match.group(1)
    return None


def find_mesen() -> Path | None:
    which = shutil.which("mesen") or shutil.which("Mesen")
    if which:
        return Path(which).resolve()
    for candidate in (
        Path("/Applications/Mesen.app/Contents/MacOS/Mesen"),
        Path("/Applications/MesenCE.app/Contents/MacOS/Mesen"),
        Path.home() / "Applications" / "Mesen.app" / "Contents" / "MacOS" / "Mesen",
    ):
        if candidate.is_file():
            return candidate
    return None


def main() -> int:
    rom = configured_rom()
    if not rom:
        print("FAIL: no ROM configured (pass a path argv, MESEN_ROM, or config/games.yaml).")
        return 1

    rom_path = Path(rom).expanduser()
    if not rom_path.is_absolute():
        rom_path = (REPO / rom_path).resolve()
    if not rom_path.is_file():
        print(f"FAIL: configured ROM path does not exist: {rom_path}")
        return 1
    if rom_path.stat().st_size <= 0:
        print(f"FAIL: configured ROM is empty: {rom_path}")
        return 1

    print(f"PASS: configured ROM path exists ({rom_path.stat().st_size} bytes): {rom_path}")

    mesen = find_mesen()
    if not mesen:
        print("WARN: Mesen executable not found on PATH or under /Applications.")
        print("      Install Mesen (download in progress), then re-run smoke_test / play.")
        print("PASS: ROM smoke check succeeded (emulator optional until installed).")
        return 0

    if not os.access(mesen, os.X_OK):
        print(f"FAIL: Mesen path is not executable: {mesen}")
        return 1

    print(f"PASS: found Mesen at {mesen}")
    if "Mesen.app" in str(mesen) or "MesenCE.app" in str(mesen):
        print("PASS: path resolves into a Mesen.app bundle (expected on macOS).")
    print("PASS: Mesen + ROM smoke check succeeded.")
    print("NOTE: Full play still requires a display and verified Mesen key bindings.")
    print(f'HINT: try: PYTHONPATH=src python3 -m nes_kickoff play')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
