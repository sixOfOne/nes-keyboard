#!/usr/bin/env python3
"""Apply keyboard bindings into MesenCE settings.json.

Quit Mesen before running this. Safe to re-run: only Nes.Port1 Mapping2/Mapping3
keyboard slots are updated (Mapping1 gamepad left alone when present).

MesenCE (Avalonia) stores controller keys as Avalonia.Input.Key integers in:

  macOS:  ~/Library/Application Support/MesenCE/settings.json
  Linux:  ~/.config/MesenCE/settings.json
  Flatpak (community placeholder, not on Flathub):
          ~/.var/app/<id>/config/MesenCE/settings.json
          (also tries .../config/mesen/ and Application Support layout)

Each controller port has Mapping1..Mapping4 OR'd together. This script writes:

  Mapping2 — WASD D-pad, X=A, Z=B, Enter=Start, LeftShift=Select
  Mapping3 — arrow D-pad, Space=A, Tab=Select

(UTF-8 with BOM matches files Mesen writes on macOS.)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


FLATPAK_APP_ID = "ca.mesen.Mesen2"
SETTINGS_NAME = "settings.json"
MESEN_DIR_NAME = "MesenCE"

# Avalonia.Input.Key values used by MesenCE KeyPresets / settings.json.
KEY = {
    "None": 0,
    "Tab": 3,
    "Enter": 6,
    "Return": 6,
    "Space": 18,
    "Left": 23,
    "Up": 24,
    "Right": 25,
    "Down": 26,
    "A": 44,
    "D": 47,
    "S": 62,
    "W": 66,
    "X": 67,
    "Z": 69,
    "LeftShift": 116,
    "RightShift": 117,
}

# Mapping2: primary WASD + face/system buttons.
MAPPING2_KEYS = {
    "Up": KEY["W"],
    "Down": KEY["S"],
    "Left": KEY["A"],
    "Right": KEY["D"],
    "A": KEY["X"],
    "B": KEY["Z"],
    "Start": KEY["Enter"],
    "Select": KEY["LeftShift"],
}

# Mapping3: arrows + alternate A/Select (Space / Tab).
MAPPING3_KEYS = {
    "Up": KEY["Up"],
    "Down": KEY["Down"],
    "Left": KEY["Left"],
    "Right": KEY["Right"],
    "A": KEY["Space"],
    "B": 0,
    "Start": 0,
    "Select": KEY["Tab"],
}

BUTTON_FIELDS = (
    "A",
    "B",
    "X",
    "Y",
    "L",
    "R",
    "Up",
    "Down",
    "Left",
    "Right",
    "Start",
    "Select",
    "U",
    "D",
    "TurboA",
    "TurboB",
    "TurboX",
    "TurboY",
    "TurboL",
    "TurboR",
    "TurboSelect",
    "TurboStart",
    "GenericKey1",
)

SPECIAL_NULL_FIELDS = (
    "PowerPadButtons",
    "FamilyBasicKeyboardButtons",
    "PartyTapButtons",
    "PachinkoButtons",
    "ExcitingBoxingButtons",
    "JissenMahjongButtons",
    "SuborKeyboardButtons",
    "BandaiMicrophoneButtons",
    "VirtualBoyButtons",
    "KonamiHyperShotButtons",
    "ArkanoidButtons",
    "ZapperButtons",
    "MouseButtons",
    "OekakidsButtons",
    "BandaiHypershotButtons",
    "NttDataKeypadButtons",
)


@dataclass
class ApplyResult:
    ok: bool
    changed: bool
    path: Path
    messages: list[str] = field(default_factory=list)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def macos_settings(home: Path) -> Path:
    return home / "Library" / "Application Support" / MESEN_DIR_NAME / SETTINGS_NAME


def linux_settings(home: Path, xdg_config_home: str | None = None) -> Path:
    if xdg_config_home:
        base = Path(xdg_config_home).expanduser()
    else:
        base = home / ".config"
    return base / MESEN_DIR_NAME / SETTINGS_NAME


def flatpak_settings(home: Path, app_id: str = FLATPAK_APP_ID) -> list[Path]:
    base = home / ".var" / "app" / app_id
    return [
        base / "config" / MESEN_DIR_NAME / SETTINGS_NAME,
        base / "config" / "mesen" / SETTINGS_NAME,
        base / "data" / MESEN_DIR_NAME / SETTINGS_NAME,
    ]


def empty_mapping() -> dict:
    out: dict = {name: None for name in SPECIAL_NULL_FIELDS}
    for name in BUTTON_FIELDS:
        out[name] = 0
    return out


def apply_keys(mapping: dict, keys: dict[str, int]) -> dict:
    out = dict(mapping) if mapping else empty_mapping()
    for name in SPECIAL_NULL_FIELDS:
        out.setdefault(name, None)
    for name in BUTTON_FIELDS:
        out.setdefault(name, 0)
    for name, code in keys.items():
        out[name] = int(code)
    return out


def find_keymap_json(explicit: str | None, home: Path) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    bundled = repo_root() / "config" / "mesen_keymap.json"
    if bundled.is_file() and Path(__file__).resolve().parent.name == "scripts":
        return bundled
    candidates = [
        home / ".config" / "nes-kickoff" / "mesen_keymap.json",
        Path(__file__).resolve().with_name("mesen_keymap.json"),
        bundled,
    ]
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def quit_mesen() -> list[str]:
    """Best-effort quit so Mesen does not overwrite settings on exit."""
    messages: list[str] = []
    if sys.platform == "darwin":
        for app in ("Mesen", "MesenCE"):
            r = subprocess.run(
                ["osascript", "-e", f'quit app "{app}"'],
                capture_output=True,
                text=True,
            )
            if r.returncode == 0:
                messages.append(f"PASS: asked {app} to quit")
        time.sleep(0.8)
    # Signal leftover Mesen emulator processes only. Do NOT match this
    # script's argv (apply_mesen_keymap.py) or ansible wrappers.
    me = os.getpid()
    try:
        out = subprocess.check_output(["pgrep", "-af", "[Mm]esen"], text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        out = ""
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if pid == me:
            continue
        cmd = parts[1]
        # Skip this apply script and unrelated paths that merely contain "mesen".
        if "apply_mesen_keymap" in cmd or "ansible" in cmd.lower():
            continue
        # Prefer real emulator binaries / app names.
        base = Path(cmd.split()[0]).name if cmd.split() else ""
        if base not in {"Mesen", "mesen", "MesenCE"} and "/Mesen" not in cmd and "MacOS/Mesen" not in cmd:
            # Still allow exact-name matches via pgrep -x fallback below.
            if "Contents/MacOS/Mesen" not in cmd and "/usr/local/lib/mesen/" not in cmd and "/usr/local/bin/mesen" not in cmd:
                continue
        try:
            os.kill(pid, signal.SIGTERM)
            messages.append(f"PASS: sent SIGTERM to pid {pid} ({cmd[:80]})")
        except OSError:
            pass
    # Exact binary name (avoids the apply script path)
    for name in ("Mesen", "mesen"):
        try:
            out = subprocess.check_output(["pgrep", "-x", name], text=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
        for pid_s in out.split():
            try:
                pid = int(pid_s)
            except ValueError:
                continue
            if pid == me:
                continue
            try:
                os.kill(pid, signal.SIGTERM)
                messages.append(f"PASS: sent SIGTERM to {name} pid {pid}")
            except OSError:
                pass
    if messages:
        time.sleep(0.5)
    else:
        messages.append("PASS: Mesen was not running")
    return messages


def load_settings(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path} root must be a JSON object")
    return data


def dump_settings(data: dict) -> str:
    # Match Mesen's indented JSON; keep UTF-8 BOM like macOS writes.
    body = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return "\ufeff" + body


def backup_settings(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_suffix(f".json.bak-{stamp}")
    n = 0
    while backup.exists():
        n += 1
        backup = path.with_suffix(f".json.bak-{stamp}-{n}")
    shutil.copy2(path, backup)
    return backup


def ensure_port1(data: dict) -> dict:
    nes = data.setdefault("Nes", {})
    if not isinstance(nes, dict):
        raise ValueError("settings Nes section must be an object")
    port1 = nes.setdefault("Port1", {})
    if not isinstance(port1, dict):
        raise ValueError("settings Nes.Port1 must be an object")
    port1.setdefault("Type", "NesController")
    port1.setdefault("TurboSpeed", 2)
    for slot in ("Mapping1", "Mapping2", "Mapping3", "Mapping4"):
        if slot not in port1 or not isinstance(port1[slot], dict):
            port1[slot] = empty_mapping()
    return port1


def mapping_matches(stored: dict | None, keys: dict[str, int]) -> bool:
    if not isinstance(stored, dict):
        return False
    for name, code in keys.items():
        if int(stored.get(name, -1)) != int(code):
            return False
    return True


def apply_to_file(path: Path, *, create: bool) -> ApplyResult:
    messages: list[str] = []
    if not path.is_file():
        if not create:
            return ApplyResult(
                ok=False,
                changed=False,
                path=path,
                messages=[
                    f"FAIL: Mesen settings not found at {path}",
                    "      Launch Mesen once so it creates settings.json, then re-run.",
                ],
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {
            "Version": "2.2.1",
            "DefaultKeyMappings": "Xbox, WasdKeys",
            "Nes": {"Port1": {"Type": "NesController", "TurboSpeed": 2}},
        }
        messages.append(f"PASS: creating new settings at {path}")
        created = True
    else:
        try:
            data = load_settings(path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            return ApplyResult(
                ok=False,
                changed=False,
                path=path,
                messages=[f"FAIL: cannot read {path}: {exc}"],
            )
        created = False

    try:
        port1 = ensure_port1(data)
    except ValueError as exc:
        return ApplyResult(
            ok=False, changed=False, path=path, messages=[f"FAIL: {exc}"]
        )

    m2_ok = mapping_matches(port1.get("Mapping2"), MAPPING2_KEYS)
    m3_ok = mapping_matches(port1.get("Mapping3"), MAPPING3_KEYS)
    if m2_ok and m3_ok and not created:
        messages.append(f"PASS: keyboard mappings already current in {path}")
        messages.append(
            "PASS: Mapping2=WASD+X/Z/Enter/Shift Mapping3=arrows+Space/Tab"
        )
        return ApplyResult(ok=True, changed=False, path=path, messages=messages)

    if not created:
        try:
            backup = backup_settings(path)
            messages.append(f"PASS: backup at {backup}")
        except OSError as exc:
            return ApplyResult(
                ok=False,
                changed=False,
                path=path,
                messages=[f"FAIL: cannot backup {path}: {exc}"],
            )

    port1["Mapping2"] = apply_keys(port1.get("Mapping2") or {}, MAPPING2_KEYS)
    port1["Mapping3"] = apply_keys(port1.get("Mapping3") or {}, MAPPING3_KEYS)
    # Leave Mapping1 (often Xbox pad) and Mapping4 untouched aside from ensure.

    try:
        path.write_text(dump_settings(data), encoding="utf-8")
    except OSError as exc:
        return ApplyResult(
            ok=False,
            changed=False,
            path=path,
            messages=[f"FAIL: cannot write {path}: {exc}"],
        )

    # Readback
    try:
        check = load_settings(path)
        cport = check["Nes"]["Port1"]
        if not mapping_matches(cport.get("Mapping2"), MAPPING2_KEYS):
            return ApplyResult(
                ok=False,
                changed=False,
                path=path,
                messages=[f"FAIL: Mapping2 readback mismatch in {path}"],
            )
        if not mapping_matches(cport.get("Mapping3"), MAPPING3_KEYS):
            return ApplyResult(
                ok=False,
                changed=False,
                path=path,
                messages=[f"FAIL: Mapping3 readback mismatch in {path}"],
            )
    except (KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
        return ApplyResult(
            ok=False,
            changed=False,
            path=path,
            messages=[f"FAIL: readback error: {exc}"],
        )

    messages.append("PASS: wrote keymap Mapping2 (WASD+X/Z/Enter/Shift)")
    messages.append("PASS: wrote keymap Mapping3 (arrows+Space/Tab)")
    messages.append(f"PASS: settings {path}")
    return ApplyResult(ok=True, changed=True, path=path, messages=messages)


def resolve_targets(
    target: str,
    home: Path,
    *,
    app_id: str,
    xdg_config_home: str | None,
    settings_override: Path | None,
) -> list[tuple[str, Path, bool]]:
    if settings_override is not None:
        return [("explicit", settings_override, True)]

    mac = ("macos", macos_settings(home), False)
    linux = ("linux", linux_settings(home, xdg_config_home), True)
    flat_paths = flatpak_settings(home, app_id)

    if target == "macos":
        return [mac]
    if target == "linux":
        return [linux]
    if target == "flatpak":
        # Prefer existing Flatpak settings file; else create under MesenCE.
        for path in flat_paths:
            if path.is_file():
                return [("flatpak", path, True)]
        return [("flatpak", flat_paths[0], True)]
    if target == "print":
        return []
    if target != "auto":
        raise ValueError(f"unknown target {target}")

    if sys.platform == "darwin":
        return [mac]
    targets = [linux]
    for path in flat_paths:
        if path.is_file():
            targets.append(("flatpak", path, True))
            break
    return targets


def find_mesen() -> Path | None:
    which = shutil.which("mesen") or shutil.which("Mesen")
    if which:
        return Path(which).resolve()
    for candidate in (
        Path("/Applications/Mesen.app/Contents/MacOS/Mesen"),
        Path("/Applications/MesenCE.app/Contents/MacOS/Mesen"),
        Path.home() / "Applications" / "Mesen.app" / "Contents" / "MacOS" / "Mesen",
        Path("/usr/local/bin/mesen"),
    ):
        if candidate.is_file():
            return candidate
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        choices=["auto", "macos", "linux", "flatpak", "print"],
        default="auto",
        help="which settings.json to update (default: auto)",
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        help="optional intent JSON (documented; bindings are coded from keymap.yaml)",
    )
    parser.add_argument(
        "--settings",
        help="write this settings.json instead of the target default path",
    )
    parser.add_argument(
        "--home",
        help="home directory used to resolve default paths",
    )
    parser.add_argument(
        "--flatpak-id",
        default=FLATPAK_APP_ID,
        help=f"Flatpak application id (default: {FLATPAK_APP_ID})",
    )
    parser.add_argument(
        "--no-quit",
        action="store_true",
        help="do not attempt to quit a running Mesen first",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    home = Path(args.home).expanduser() if args.home else Path.home()
    intent = find_keymap_json(args.json_path, home)
    print(f"Keymap intent: {intent if intent.is_file() else '(built-in Avalonia codes)'}")
    print(
        "Bindings: WASD+arrows D-pad; X/Space=A; Z=B; Enter=Start; Shift/Tab=Select"
    )
    print(
        "NOTE: quit Mesen before applying; a running app can overwrite settings on exit."
    )

    if not args.no_quit and args.target != "print":
        for line in quit_mesen():
            print(line)

    mesen = find_mesen()
    if mesen:
        print(f"PASS: found Mesen at {mesen}")
    else:
        print("WARN: Mesen binary not found on PATH / Applications /usr/local/bin.")

    xdg = None if args.home else os.environ.get("XDG_CONFIG_HOME")
    override = Path(args.settings).expanduser() if args.settings else None
    try:
        targets = resolve_targets(
            args.target,
            home,
            app_id=args.flatpak_id,
            xdg_config_home=xdg,
            settings_override=override,
        )
    except ValueError as exc:
        print(f"FAIL: {exc}")
        return 1

    if args.target == "print":
        print("Mapping2:", MAPPING2_KEYS)
        print("Mapping3:", MAPPING3_KEYS)
        print("PASS: print-only (no settings written)")
        return 0

    failed = False
    any_changed = False
    for label, path, create in targets:
        print(f"Target: {label} -> {path}")
        result = apply_to_file(path, create=create)
        for line in result.messages:
            print(line)
        if not result.ok:
            failed = True
        if result.changed:
            any_changed = True

    if failed:
        return 1
    if any_changed:
        print("NOTE: relaunch Mesen to pick up the mapping.")
    print("PASS: keymap apply complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
