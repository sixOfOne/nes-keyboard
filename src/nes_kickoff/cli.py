"""CLI for the local-first NES kickoff."""
from __future__ import annotations

import argparse
import os
import json
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - optional until deps installed
    yaml = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GAMES = REPO_ROOT / "config" / "games.yaml"

# AWS / remote play defaults
SSH_USER = "ec2-user"
SSH_KEY_DEFAULT = Path.home() / ".ssh" / "neo-atari.pem"
REMOTE_ROM_DIR = "~/roms"  # expands on the remote host to /home/ec2-user/roms
FLATPAK_MESEN = "ca.mesen.Mesen2"
VNC_DISPLAY = ":1"
VNC_PORT = 5901
VNC_LOCAL_URL = f"vnc://127.0.0.1:{VNC_PORT}"
# Installed by configure --target aws. The wrapper keeps software video and
# turns on PulseAudio only after the PipeWire "mesen" sink is ready.
REMOTE_MESEN_BIN = "/usr/local/bin/mesen-flatpak"
REMOTE_AUDIO_CAPTURE_BIN = "/usr/local/bin/mesen-audio-capture"
REMOTE_AUDIO_MODE_FILE = "/tmp/nes-kickoff-audio-mode"
REMOTE_MESEN_LOG = "/tmp/nes-kickoff-mesen.log"
# auto: pulse when the sink and Flatpak socket are up, else dummy (no crash).
# on: same path, with a warning if it falls back. off: dummy (--no-audio).
AUDIO_AUTO = "auto"
AUDIO_ON = "on"
AUDIO_OFF = "off"
AUDIO_MODES = (AUDIO_AUTO, AUDIO_ON, AUDIO_OFF)
# TigerVNC does not forward audio. Capture is raw s16le 48 kHz stereo from
# the mesen sink (pw-cat --target mesen). Keep in sync with mesen-audio-capture.
REMOTE_AUDIO_RATE = "48000"
REMOTE_AUDIO_CHANNELS = "2"
VNC_AUDIO_LOG = Path.home() / ".cache" / "nes-kickoff" / "vnc-audio.log"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Keyboard-controlled NES kickoff")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("up", help="placeholder: start the local smoke path")
    apply = subparsers.add_parser(
        "apply", help="run Terraform (local-ready by default; AWS when enable_aws=true)"
    )
    apply.add_argument(
        "--dry-run",
        action="store_true",
        help="run terraform plan instead of apply",
    )
    apply.add_argument(
        "--init",
        action="store_true",
        help="run terraform init before plan/apply",
    )

    configure = subparsers.add_parser(
        "configure", help="run Ansible to configure Mesen (local or aws inventory)"
    )
    configure.add_argument(
        "--target",
        choices=["local", "aws"],
        default="local",
        help="inventory target: local (default) or aws (from Terraform outputs)",
    )
    configure.add_argument(
        "--dry-run", action="store_true", help="print the Ansible command only"
    )

    play = subparsers.add_parser("play", help="launch Mesen with a ROM")
    play.add_argument(
        "rom",
        nargs="?",
        help="ROM path (absolute, relative to repo, or a game name from config/games.yaml)",
    )
    play.add_argument(
        "--target",
        choices=["local", "aws"],
        default="local",
        help="where to launch: local Mesen (default) or AWS EC2 + VNC",
    )
    play.add_argument(
        "--foreground",
        action="store_true",
        help="run Mesen in the foreground (local: blocks until quit; aws: keep SSH session open)",
    )
    audio_flags = play.add_mutually_exclusive_group()
    audio_flags.add_argument(
        "--audio",
        dest="audio",
        action="store_const",
        const=AUDIO_ON,
        help=(
            "request remote audio (also the default when the PipeWire sink is up). "
            "Falls back to silent instead of crashing if the sink is missing"
        ),
    )
    audio_flags.add_argument(
        "--no-audio",
        dest="audio",
        action="store_const",
        const=AUDIO_OFF,
        help="launch Mesen silent (dummy SDL driver) if audio init crashes",
    )
    play.set_defaults(audio=AUDIO_AUTO)
    play.add_argument(
        "--dry-run",
        action="store_true",
        help="print the launch (and sync) command(s) without running them",
    )
    play.add_argument(
        "--ssh-key",
        default=str(SSH_KEY_DEFAULT),
        help=f"SSH private key for AWS target (default: {SSH_KEY_DEFAULT})",
    )
    play.add_argument(
        "--vnc-tunnel",
        action="store_true",
        help=(
            "with --target aws, print the SSH local-forward command and "
            f"{VNC_LOCAL_URL}, then exit (no ROM sync)"
        ),
    )
    return parser


def load_games_config() -> list:
    if not DEFAULT_GAMES.is_file():
        return []
    text = DEFAULT_GAMES.read_text(encoding="utf-8")
    if yaml is not None:
        data = yaml.safe_load(text) or {}
        return list(data.get("games") or [])
    games = []
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- name:"):
            if current:
                games.append(current)
            current = {"name": stripped.split(":", 1)[1].strip().strip("\"'" )}
        elif stripped.startswith("rom:") and current is not None:
            current["rom"] = stripped.split(":", 1)[1].strip().strip("\"'" )
    if current:
        games.append(current)
    return games


def resolve_rom(rom_arg):
    games = load_games_config()
    if rom_arg is None:
        if not games:
            raise SystemExit(
                "No ROM given and config/games.yaml has no games. "
                "Pass a ROM path or add an entry under games:."
            )
        rom_arg = str(games[0].get("rom") or "")
        if not rom_arg:
            raise SystemExit("First games.yaml entry is missing a rom: path.")
    else:
        for game in games:
            name = str(game.get("name") or "").lower()
            if name and name == rom_arg.lower():
                rom_arg = str(game.get("rom") or "")
                break

    path = Path(rom_arg).expanduser()
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    else:
        path = path.resolve()

    if not path.is_file():
        raise SystemExit(f"ROM not found: {path}")
    if path.stat().st_size <= 0:
        raise SystemExit(f"ROM is empty: {path}")
    return path


def find_mesen_binary():
    which = shutil.which("mesen") or shutil.which("Mesen")
    if which:
        return Path(which).resolve()
    for mac_app in (
        Path("/Applications/Mesen.app/Contents/MacOS/Mesen"),
        Path("/Applications/MesenCE.app/Contents/MacOS/Mesen"),
        Path.home() / "Applications" / "Mesen.app" / "Contents" / "MacOS" / "Mesen",
    ):
        if mac_app.is_file():
            return mac_app
    return None


def _macos_mesen_app() -> Path | None:
    for app in (
        Path("/Applications/Mesen.app"),
        Path("/Applications/MesenCE.app"),
        Path.home() / "Applications" / "Mesen.app",
    ):
        if app.exists():
            return app
    return None


def launch_command(rom, *, foreground: bool):
    if platform.system() == "Darwin" and not foreground:
        app = _macos_mesen_app()
        if app is not None:
            return ["open", "-a", app.name.replace(".app", ""), "--args", str(rom)]
    mesen = find_mesen_binary()
    if not mesen:
        raise SystemExit(
            "Mesen not found on PATH and no Mesen.app under /Applications "
            "(install still in progress is OK — re-run play after it lands)."
        )
    return [str(mesen), str(rom)]


def _fmt_cmd(cmd: list[str]) -> str:
    return " ".join(shlex.quote(c) for c in cmd)


def resolve_aws_ssh_host() -> str:
    """Return the EC2 public IP from Terraform outputs, or exit with a clear error."""
    tf_dir = REPO_ROOT / "terraform"
    if not (tf_dir / "main.tf").is_file():
        raise SystemExit(f"Terraform files missing under {tf_dir}")
    terraform = shutil.which("terraform")
    if not terraform:
        raise SystemExit(
            "terraform not found on PATH. Install Terraform "
            "(e.g. brew install hashicorp/tap/terraform) to resolve the AWS host."
        )
    try:
        raw = subprocess.check_output(
            [terraform, "output", "-json"],
            cwd=str(tf_dir),
            text=True,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or "").strip() or str(exc)
        raise SystemExit(
            "Failed to read Terraform outputs. Run "
            "`PYTHONPATH=src python3 -m nes_kickoff apply` with enable_aws=true first.\n"
            f"Detail: {err}"
        ) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Terraform output -json was not valid JSON: {exc}") from exc

    mode = (data.get("mode") or {}).get("value")
    ip = (data.get("public_ip") or {}).get("value") or (
        data.get("ssh_host") or {}
    ).get("value")
    if mode != "aws" or not ip:
        raise SystemExit(
            "AWS host unavailable: Terraform mode is not 'aws' or public_ip/ssh_host "
            "is empty. Set enable_aws=true in terraform/terraform.tfvars and run "
            "`PYTHONPATH=src python3 -m nes_kickoff apply`."
        )
    return str(ip)


def vnc_tunnel_argv(host: str, key: Path) -> list[str]:
    """SSH local forward. TigerVNC listens on the instance loopback only."""
    return [
        "ssh",
        "-i",
        str(key),
        "-L",
        f"{VNC_PORT}:127.0.0.1:{VNC_PORT}",
        f"{SSH_USER}@{host}",
    ]


def print_vnc_tunnel(host: str, key: Path) -> None:
    print(
        f"VNC listens on 127.0.0.1:{VNC_PORT} on the instance. "
        f"TCP {VNC_PORT} is not open on the security group."
    )
    print("Tunnel:", _fmt_cmd(vnc_tunnel_argv(host, key)))
    print(f"Then connect: {VNC_LOCAL_URL}")


def ssh_base_args(host: str, key: Path) -> list[str]:
    return [
        "ssh",
        "-i",
        str(key),
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "BatchMode=yes",
        f"{SSH_USER}@{host}",
    ]


def scp_base_args(key: Path) -> list[str]:
    return [
        "scp",
        "-i",
        str(key),
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "BatchMode=yes",
    ]


def remote_rom_path(rom: Path) -> str:
    """Absolute remote path under ~/roms (quoted-safe basename preserved)."""
    # Keep the original filename so Mesen / VNC users recognize it.
    return f"/home/{SSH_USER}/roms/{rom.name}"


def build_remote_mkdir_cmd() -> str:
    return f"mkdir -p {REMOTE_ROM_DIR}"


def _validate_audio_mode(audio: str) -> str:
    if audio not in AUDIO_MODES:
        raise ValueError(f"audio mode must be one of {AUDIO_MODES}, got {audio!r}")
    return audio


def build_remote_mesen_cmd(remote_rom: str, *, foreground: bool, audio: str = AUDIO_AUTO) -> str:
    """Shell snippet run on the EC2 host to launch Flatpak Mesen on the VNC display.

    Software video stays on inside mesen-flatpak. Audio is NES_AUDIO:
    the wrapper uses PulseAudio only when the PipeWire sink and the Flatpak
    socket are both ready, and otherwise keeps the dummy driver.
    """
    audio = _validate_audio_mode(audio)
    rom_q = shlex.quote(remote_rom)
    exports = [
        f"export DISPLAY={shlex.quote(VNC_DISPLAY)}",
        "export XAUTHORITY=$HOME/.Xauthority",
        'export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"',
        f"export NES_AUDIO={shlex.quote(audio)}",
    ]
    run = f"{REMOTE_MESEN_BIN} {rom_q}"
    prefix = "; ".join(exports) + "; "
    if foreground:
        return prefix + run
    # Detach so the local CLI returns. The mode file is written only after
    # the wrapper decides pulse vs dummy, so wait until it exists.
    mode_q = shlex.quote(REMOTE_AUDIO_MODE_FILE)
    return (
        prefix
        + f"rm -f {mode_q}; "
        + f"nohup {run} >{shlex.quote(REMOTE_MESEN_LOG)} 2>&1 </dev/null & "
        + "echo $!; "
        + "for _ in $(seq 1 50); do "
        + f"if [ -s {mode_q} ]; then cat {mode_q}; exit 0; fi; "
        + "sleep 0.2; done; echo unknown"
    )


def build_remote_audio_capture_cmd() -> str:
    """Shell snippet that writes raw PCM for the Mesen sink to stdout."""
    return (
        'export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"; '
        'if [ -S "$XDG_RUNTIME_DIR/bus" ]; then '
        'export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"; '
        "fi; "
        f"exec {REMOTE_AUDIO_CAPTURE_BIN}"
    )


def _resolve_bin(*candidates: str) -> str | None:
    """Return the first existing executable path from candidates or PATH names."""
    for candidate in candidates:
        if "/" in candidate:
            path = Path(candidate)
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
        else:
            found = shutil.which(candidate)
            if found:
                return found
    return None


def local_pcm_player_command() -> list[str] | None:
    """Local player for the remote s16le 48 kHz stereo stream, if one exists.

    Prefer sox `play` (Homebrew path first): ffplay on raw s16le is unreliable
    on some Macs. Fall back to ffmpeg AudioToolbox, then ffplay, then mpv.
    """
    play_bin = _resolve_bin("/opt/homebrew/bin/play", "play")
    if play_bin:
        return [
            play_bin,
            "-q",
            "-t",
            "raw",
            "-r",
            REMOTE_AUDIO_RATE,
            "-e",
            "signed-integer",
            "-b",
            "16",
            "-c",
            REMOTE_AUDIO_CHANNELS,
            "-",
        ]
    ffmpeg = _resolve_bin("/opt/homebrew/bin/ffmpeg", "ffmpeg")
    if ffmpeg:
        return [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "s16le",
            "-ar",
            REMOTE_AUDIO_RATE,
            "-ac",
            REMOTE_AUDIO_CHANNELS,
            "-i",
            "pipe:0",
            "-f",
            "audiotoolbox",
            "default",
        ]
    if shutil.which("ffplay"):
        return [
            "ffplay",
            "-nodisp",
            "-autoexit",
            "-loglevel",
            "error",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-probesize",
            "32",
            "-analyzeduration",
            "0",
            "-f",
            "s16le",
            "-ar",
            REMOTE_AUDIO_RATE,
            "-ch_layout",
            "stereo",
            "-i",
            "pipe:0",
        ]
    if shutil.which("mpv"):
        return [
            "mpv",
            "--no-video",
            "--really-quiet",
            "--demuxer=rawaudio",
            f"--demuxer-rawaudio-rate={REMOTE_AUDIO_RATE}",
            f"--demuxer-rawaudio-channels={REMOTE_AUDIO_CHANNELS}",
            "--demuxer-rawaudio-format=s16le",
            "-",
        ]
    return None


def parse_remote_launch_output(stdout: str) -> tuple[str, str]:
    """Return (pid, audio driver) from the detached launch command."""
    lines = [line.strip() for line in (stdout or "").splitlines() if line.strip()]
    pid = lines[0] if lines else "(unknown)"
    mode = lines[1] if len(lines) > 1 else "unknown"
    return pid, mode


def start_remote_audio_stream(
    ssh_cmd: list[str],
    player: list[str],
    *,
    detach: bool,
) -> tuple[subprocess.Popen[bytes], subprocess.Popen[bytes]]:
    """Pipe remote PCM into a local player.

    detach=True starts a new session so audio survives this CLI exit.
    Prefer detach=False so audio stays in this Terminal's session: closing
    the Terminal stops sound; leaving it open keeps sound.
    """
    VNC_AUDIO_LOG.parent.mkdir(parents=True, exist_ok=True)
    log_file = VNC_AUDIO_LOG.open("ab")
    ssh_proc: subprocess.Popen[bytes] | None = None
    try:
        ssh_proc = subprocess.Popen(
            ssh_cmd,
            stdout=subprocess.PIPE,
            stderr=log_file,
            start_new_session=detach,
        )
        player_proc = subprocess.Popen(
            player,
            stdin=ssh_proc.stdout,
            stdout=log_file,
            stderr=log_file,
            start_new_session=detach,
        )
    except Exception:
        if ssh_proc is not None and ssh_proc.poll() is None:
            ssh_proc.kill()
            try:
                ssh_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
        log_file.close()
        raise
    if ssh_proc.stdout is not None:
        ssh_proc.stdout.close()
    log_file.close()
    return ssh_proc, player_proc


def stop_remote_audio_stream(
    procs: tuple[subprocess.Popen[bytes], subprocess.Popen[bytes]] | None,
) -> None:
    if not procs:
        return
    for proc in procs:
        if proc.poll() is None:
            proc.terminate()
    for proc in procs:
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)


def _audio_listen_ssh(host: str, key: Path) -> list[str]:
    return ssh_base_args(host, key) + [build_remote_audio_capture_cmd()]


def _print_audio_plan(host: str, key: Path, audio: str) -> list[str] | None:
    """Print how audio will be heard. Return the local player command, if any."""
    if audio == AUDIO_OFF:
        print("Audio: off (dummy SDL driver).")
        return None
    player = local_pcm_player_command()
    listen = _audio_listen_ssh(host, key)
    if player is None:
        print(
            "Audio: remote sink only. No local player (sox play, ffmpeg, or ffplay). "
            "Install sox (`brew install sox`) or ffmpeg and re-run play to hear it. "
            f"Log path when a player is used: {VNC_AUDIO_LOG}"
        )
        print("   Remote capture:", _fmt_cmd(listen))
        return None
    print(
        "4) Hear audio (when the driver is pulseaudio):",
        _fmt_cmd(listen) + " | " + _fmt_cmd(player),
    )
    return player


def _begin_audio_stream(
    host: str,
    key: Path,
    player: list[str] | None,
    *,
    detach: bool,
) -> tuple[subprocess.Popen[bytes], subprocess.Popen[bytes]] | None:
    if player is None:
        return None
    procs = start_remote_audio_stream(
        _audio_listen_ssh(host, key), player, detach=detach
    )
    print(f"Audio streaming to this machine (player pid {procs[1].pid}); log: {VNC_AUDIO_LOG}")
    return procs


def cmd_play_aws(
    rom_arg,
    *,
    dry_run: bool,
    foreground: bool,
    ssh_key: str,
    audio: str = AUDIO_AUTO,
) -> int:
    audio = _validate_audio_mode(audio)
    rom = resolve_rom(rom_arg)
    key = Path(ssh_key).expanduser()
    if not dry_run and not key.is_file():
        raise SystemExit(
            f"SSH key not found: {key}. Pass --ssh-key or place neo-atari.pem at "
            f"{SSH_KEY_DEFAULT}."
        )

    host = resolve_aws_ssh_host()
    remote_rom = remote_rom_path(rom)
    mkdir_remote = build_remote_mkdir_cmd()
    scp_cmd = scp_base_args(key) + [str(rom), f"{SSH_USER}@{host}:{remote_rom}"]
    launch_remote = build_remote_mesen_cmd(
        remote_rom, foreground=foreground, audio=audio
    )
    ssh_mkdir = ssh_base_args(host, key) + [mkdir_remote]
    ssh_launch = ssh_base_args(host, key) + [launch_remote]

    print(f"Target: aws ({SSH_USER}@{host})")
    print(f"ROM (local): {rom}")
    print(f"ROM (remote): {remote_rom}")
    print(f"Keymap: {REPO_ROOT / 'config' / 'keymap.yaml'}")
    print(
        "Launch profile: software video; "
        f"audio {audio} (PipeWire pulse when the mesen sink is up, else silent)"
    )
    print(f"VNC display: {VNC_DISPLAY} on the instance loopback")
    print_vnc_tunnel(host, key)
    print("1) Ensure remote ROM dir:", _fmt_cmd(ssh_mkdir))
    print("2) Sync ROM:", _fmt_cmd(scp_cmd))
    print("3) Launch Mesen:", _fmt_cmd(ssh_launch))
    player = _print_audio_plan(host, key, audio)

    if dry_run:
        print("Dry run only; no SSH/SCP performed.")
        return 0

    for label, cmd in (
        ("mkdir", ssh_mkdir),
        ("scp", scp_cmd),
    ):
        completed = subprocess.run(cmd, check=False)
        if completed.returncode != 0:
            print(f"FAIL: {label} exited {completed.returncode}", file=sys.stderr)
            return completed.returncode

    if foreground:
        print("Starting remote Mesen in the foreground (quit Mesen / Ctrl-C to return).")
        listener = _begin_audio_stream(host, key, player, detach=False)
        if listener is not None:
            print("Leave this Terminal open for remote audio.")
        try:
            completed = subprocess.run(ssh_launch, check=False)
            return completed.returncode
        finally:
            stop_remote_audio_stream(listener)

    completed = subprocess.run(ssh_launch, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        print(
            f"FAIL: remote launch exited {completed.returncode}\n"
            f"stdout: {completed.stdout}\nstderr: {completed.stderr}",
            file=sys.stderr,
        )
        return completed.returncode
    pid_msg, mode = parse_remote_launch_output(completed.stdout or "")
    print(f"Mesen launched on AWS (remote pid ~{pid_msg}); log: {REMOTE_MESEN_LOG}")
    print(f"View via VNC: {VNC_LOCAL_URL} (keep the SSH tunnel open)")
    if audio == AUDIO_OFF or mode == "dummy":
        if audio == AUDIO_ON:
            print(
                "Audio requested, but the PipeWire sink or Flatpak socket was not ready. "
                f"Mesen is silent. Log: {REMOTE_MESEN_LOG}",
                file=sys.stderr,
            )
        else:
            print("Audio: silent (dummy SDL driver). Re-run configure --target aws if this is unexpected.")
        return 0
    print(f"Audio driver: {mode}")
    # Keep audio in this Terminal's session (no start_new_session). Agent-started
    # detached streams get killed; the user must leave this Terminal open.
    listener = _begin_audio_stream(host, key, player, detach=False)
    if listener is not None:
        print("Leave this Terminal open for remote audio.")
    return 0


def cmd_play(
    rom_arg,
    *,
    foreground: bool,
    dry_run: bool,
    target: str = "local",
    ssh_key: str = str(SSH_KEY_DEFAULT),
    audio: str = AUDIO_AUTO,
    vnc_tunnel: bool = False,
) -> int:
    if vnc_tunnel and target != "aws":
        raise SystemExit("--vnc-tunnel applies to --target aws.")
    if target == "aws" and vnc_tunnel:
        host = resolve_aws_ssh_host()
        print_vnc_tunnel(host, Path(ssh_key).expanduser())
        return 0
    if target == "aws":
        return cmd_play_aws(
            rom_arg,
            dry_run=dry_run,
            foreground=foreground,
            ssh_key=ssh_key,
            audio=audio,
        )

    if audio != AUDIO_AUTO:
        print("Note: --audio and --no-audio apply to --target aws. Local Mesen is unchanged.")
    rom = resolve_rom(rom_arg)
    cmd = launch_command(rom, foreground=foreground)
    print(f"ROM: {rom}")
    print(f"Keymap: {REPO_ROOT / 'config' / 'keymap.yaml'}")
    print("Launch:", " ".join(f'"{c}"' if " " in c else c for c in cmd))
    if dry_run:
        print("Dry run only; Mesen not started.")
        return 0
    if (
        platform.system() == "Darwin"
        and not foreground
        and len(cmd) >= 3
        and cmd[0] == "open"
        and cmd[1] == "-a"
    ):
        subprocess.run(cmd, check=False)
        print("Mesen launched via open (terminal stays free).")
        return 0
    print("Starting Mesen in the foreground (quit the app to return to the shell).")
    completed = subprocess.run(cmd, check=False)
    return completed.returncode


def cmd_configure(*, target: str = "local", dry_run: bool = False) -> int:
    playbook = REPO_ROOT / "ansible" / "playbook.yml"
    if not playbook.is_file():
        raise SystemExit(f"Ansible playbook missing: {playbook}")
    ansible = shutil.which("ansible-playbook")
    if not ansible:
        raise SystemExit(
            "ansible-playbook not found on PATH. Install Ansible (e.g. brew install ansible)."
        )

    if target == "aws":
        render = REPO_ROOT / "scripts" / "render_aws_inventory.py"
        code = subprocess.run([sys.executable, str(render)], check=False).returncode
        if code != 0:
            return code
        inventory = REPO_ROOT / "ansible" / "inventory" / "aws.yml"
    else:
        inventory = REPO_ROOT / "ansible" / "inventory" / "localhost.yml"

    if not inventory.is_file():
        raise SystemExit(f"Inventory missing: {inventory}")

    cmd = [ansible, "-i", str(inventory), str(playbook)]
    print("Launch:", " ".join(cmd))
    if dry_run:
        print("Dry run only; Ansible not started.")
        if target == "aws":
            print_vnc_tunnel(resolve_aws_ssh_host(), SSH_KEY_DEFAULT)
        return 0
    completed = subprocess.run(cmd, cwd=str(REPO_ROOT / "ansible"), check=False)
    if target == "aws" and completed.returncode == 0:
        print_vnc_tunnel(resolve_aws_ssh_host(), SSH_KEY_DEFAULT)
    return completed.returncode


def cmd_apply(*, dry_run: bool = False, do_init: bool = False) -> int:
    tf_dir = REPO_ROOT / "terraform"
    if not (tf_dir / "main.tf").is_file():
        raise SystemExit(f"Terraform files missing under {tf_dir}")
    terraform = shutil.which("terraform")
    if not terraform:
        raise SystemExit(
            "terraform not found on PATH. Install Terraform (e.g. brew install hashicorp/tap/terraform)."
        )

    def run(cmd: list[str]) -> int:
        print("Launch:", " ".join(cmd))
        return subprocess.run(cmd, cwd=str(tf_dir), check=False).returncode

    if do_init or not (tf_dir / ".terraform").exists():
        code = run([terraform, "init", "-input=false"])
        if code != 0:
            return code

    action = "plan" if dry_run else "apply"
    cmd = [terraform, action, "-input=false"]
    if action == "apply":
        cmd.append("-auto-approve")
    return run(cmd)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "up":
        print("UP placeholder: would start the local Mesen smoke path.")
        return 0
    if args.command == "apply":
        return cmd_apply(dry_run=args.dry_run, do_init=args.init)
    if args.command == "configure":
        return cmd_configure(target=args.target, dry_run=args.dry_run)
    if args.command == "play":
        return cmd_play(
            args.rom,
            foreground=args.foreground,
            dry_run=args.dry_run,
            target=args.target,
            ssh_key=args.ssh_key,
            audio=args.audio,
            vnc_tunnel=args.vnc_tunnel,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
