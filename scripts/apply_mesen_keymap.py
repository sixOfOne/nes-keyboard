#!/usr/bin/env python3
"""Apply config/mesen_keymap.json into a local Mesen settings store (stub).

Mesen's on-disk input format differs from Stella's sqlite keymap_joy and is
still being verified against the build Jeremy is installing. Until a known
settings path + schema are confirmed, this script:

  1. Loads the project keymap intent (YAML + JSON stub).
  2. Detects whether a Mesen binary / app bundle is present.
  3. Prints the intended WASD/arrows/A/B/Start/Select map.
  4. Exits 0 with a clear "stub" message when Mesen is missing, or when the
     settings writer is not yet implemented for the detected build.

Re-run after Mesen is installed. Safe to call from Ansible.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DEFAULT_JSON = REPO / "config" / "mesen_keymap.json"
DEFAULT_YAML = REPO / "config" / "keymap.yaml"

# Community Flatpak id from joshas/Mesen2-flatpak — NOT published on Flathub.
# Prefer nesdev-org/MesenCE GitHub release binaries / AppImage on Linux.
FLATPAK_APP_ID = "ca.mesen.Mesen2"


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


def load_stub(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        choices=["auto", "macos", "flatpak", "print"],
        default="auto",
        help="Where to write (stub: only print is fully implemented)",
    )
    parser.add_argument("--flatpak-id", default=FLATPAK_APP_ID)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    args = parser.parse_args(argv)

    if not args.json.is_file():
        print(f"FAIL: keymap stub missing: {args.json}", file=sys.stderr)
        return 1

    stub = load_stub(args.json)
    print(f"Keymap stub: {args.json}")
    if DEFAULT_YAML.is_file():
        print(f"Intent YAML: {DEFAULT_YAML}")
    for binding in stub.get("bindings") or []:
        action = binding.get("action")
        keys = ", ".join(binding.get("keys") or [])
        print(f"  {action}: {keys}")

    mesen = find_mesen()
    if mesen:
        print(f"PASS: found Mesen at {mesen}")
    else:
        print("WARN: Mesen binary not found on PATH or under /Applications.")
        print("      Install Mesen (download in progress), then re-run this script.")

    if args.target == "flatpak":
        print(
            f"NOTE: Flatpak id {args.flatpak_id} is a community placeholder "
            "(not on Flathub). Prefer a GitHub release / AppImage on Amazon Linux."
        )

    print(
        "STUB: settings writer not implemented for this Mesen build yet. "
        "Intent files are in place; no settings database was modified."
    )
    print("PASS: keymap stub check complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
