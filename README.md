# nes-keyboard

Keyboard-controlled NES / Game Boy (and SNES/GBA-ready) play via [MesenCE](https://github.com/nesdev-org/MesenCE), with a Python kickoff CLI, Ansible for host config, and Terraform for an optional AWS EC2 host.

Modeled on `atari-keyboard` (Stella). Emulator: **MesenCE**. Bundled local examples: Super Mario Bros (`.nes`) and Tetris (`.gb`).

## What’s working today

- **Local (macOS):** Mesen.app + `~/.local/bin/mesen` symlink, WASD/arrows/A/B/Start/Select keymap for **NES Port1** and **Game Boy Controller**, Mario + Tetris under `roms/` (gitignored), smoke test, `play` / `configure` / `apply` CLI with `--system nes|gb|snes|gba`.
- **MesenCE keymap:** `scripts/apply_mesen_keymap.py` writes Avalonia key codes into `~/Library/Application Support/MesenCE/settings.json` (`Nes.Port1` + `Gameboy.Controller` Mapping2/Mapping3). Linux: `~/.config/MesenCE/settings.json`.
- **AWS (us-east-2):** EC2 `t3.small`, 20 GB gp3 root (desktop stack + MesenCE zip need more than 8 GB), SSH locked to your IP. Ansible inventory from Terraform outputs. MesenCE from GitHub release zip; **SDL2** comes from a pinned Fedora 36 RPM (AL2023 does not ship `libSDL2`).
- **AWS VNC:** TigerVNC on display `:1`, bound to **127.0.0.1:5901** (not in the security group). Password only in `~/.config/nes-kickoff/vnc-password.txt` (mode 600, never committed). Connect through an SSH tunnel, then `vnc://127.0.0.1:5901`.
- **Remote play:** `play --target aws` syncs a ROM over SCP to `~/roms/` on EC2 and launches Mesen on `DISPLAY=:1`. Audio uses a PipeWire null sink (`mesen`) when that server is up; TigerVNC carries the picture only; the CLI plays the sink back on this machine over SSH.

## Layout

```
config/           keymap + mesen_keymap.json + games.yaml
roms/             local ROMs only (gitignored; keep .gitkeep)
scripts/          smoke_test, apply_mesen_keymap, render_aws_inventory
src/nes_kickoff   CLI entrypoint
ansible/          localhost + aws inventories, sshd + mesen roles
terraform/        local marker by default; EC2 when enable_aws=true
```

## Local quick start

1. Install MesenCE (macOS build from [releases](https://github.com/nesdev-org/MesenCE/releases)). Symlink if needed:
   `ln -sfn /Applications/Mesen.app/Contents/MacOS/Mesen ~/.local/bin/mesen`
2. Place ROMs under `roms/` and list them in `config/games.yaml` (e.g. `Super_Mario_Bros.nes`, `Tetris.gb`).
3. Apply keymap (quit Mesen first):
   `python3 scripts/apply_mesen_keymap.py`
4. Smoke check:
   `python3 scripts/smoke_test.py`
5. Play (always set `PYTHONPATH`):

```bash
PYTHONPATH=src python3 -m nes_kickoff play --system nes "Super Mario Bros"
PYTHONPATH=src python3 -m nes_kickoff play --system gb Tetris
```

Omit `--system` to infer from the ROM extension or `games.yaml`. On macOS, `play` uses `open -a Mesen` so the terminal does not block.

Optional local Ansible (symlink + keymap):

`PYTHONPATH=src python3 -m nes_kickoff configure --target local`

### Flatpak / Linux note

There is **no official Mesen on Flathub**. Community builds exist (placeholder id `ca.mesen.Mesen2`). On Amazon Linux prefer the GitHub release zip linked as `/usr/local/bin/mesen`. The `mesen-flatpak` wrapper tries that binary first.

## AWS path

1. Copy `terraform/terraform.tfvars.example` → `terraform/terraform.tfvars` (gitignored).
2. Set `enable_aws`, `aws_region`, `key_name`, and `ssh_ingress_cidr` (your `/32`). SSH stays open to that CIDR. VNC is not a security-group port (`enable_vnc` in tfvars is ignored).
3. Keep the private key at `~/.ssh/<name>.pem` mode `600` — never in the repo. Default reuses `neo-atari` / `~/.ssh/neo-atari.pem`.
4. Credentials via `~/.aws/credentials`.
5. Apply / configure / SSH:

```bash
PYTHONPATH=src python3 -m nes_kickoff apply --dry-run
PYTHONPATH=src python3 -m nes_kickoff apply
PYTHONPATH=src python3 -m nes_kickoff configure --target aws
ssh -i ~/.ssh/neo-atari.pem ec2-user@$(cd terraform && terraform output -raw public_ip)
```

`configure --target aws` installs MesenCE, the Fedora SDL2 RPM for `MesenCore.so`, TigerVNC, PipeWire, and `/etc/ssh/sshd_config.d/00-nes-keyboard-hardening.conf`. It reloads sshd only after `sshd -t` and `sshd -T` both accept it (`PasswordAuthentication no`, `KbdInteractiveAuthentication no`, `PermitRootLogin no`, `PubkeyAuthentication yes`). Confirm `.pem` login works before that reload.

### SDL2 on Amazon Linux 2023

AL2023 does not package SDL2 (`libSDL2-2.0.so.0`), which MesenCore needs. Ansible pins a Fedora 36 RPM (glibc-compatible with AL2023) via `mesen_sdl2_rpm_url` in `ansible/roles/mesen/defaults/main.yml` and installs `libdecor` alongside it.

### Remote desktop (VNC via SSH tunnel)

The security group allows SSH only. Ansible binds TigerVNC to localhost (`localhost` in `/etc/tigervnc/vncserver-config-mandatory`) and enables `vncserver@:1`.

1. Password file on the Mac (create once; never commit):

```bash
mkdir -p ~/.config/nes-kickoff
# VNC passwords are effectively 8 characters
openssl rand -base64 6 | tr -d '/+=' | head -c 8 > ~/.config/nes-kickoff/vnc-password.txt
chmod 600 ~/.config/nes-kickoff/vnc-password.txt
```

2. Apply + configure, then tunnel (leave SSH open):

```bash
ssh -i ~/.ssh/neo-atari.pem -L 5901:127.0.0.1:5901 ec2-user@HOST
```

`HOST` is `cd terraform && terraform output -raw public_ip`. The same command is printed by `play --target aws` and by `play --target aws --vnc-tunnel`.

- **Screen Sharing / Finder → Go → Connect to Server:** `vnc://127.0.0.1:5901`
- Password: contents of `~/.config/nes-kickoff/vnc-password.txt`

3. Remote play from the Mac:

```bash
PYTHONPATH=src python3 -m nes_kickoff play --target aws --dry-run
PYTHONPATH=src python3 -m nes_kickoff play --system nes "Super Mario Bros" --target aws
PYTHONPATH=src python3 -m nes_kickoff play --system gb Tetris --target aws
```

SSH identity defaults to `~/.ssh/neo-atari.pem` (`--ssh-key` to override). Host comes from Terraform outputs. Use `--foreground` to keep the SSH session attached. `--no-audio` forces the silent driver.

### Remote audio

TigerVNC carries picture + keyboard only. `configure --target aws` installs PipeWire and a null sink named `mesen`. `play --target aws` streams raw PCM over SSH into local `sox play` / `ffmpeg` / `ffplay`. Leave that Terminal open for sound. Log: `~/.cache/nes-kickoff/vnc-audio.log`.

## CLI cheat sheet

| Command | Purpose |
|--------|---------|
| `play [--system nes\|gb\|snes\|gba] [--target local\|aws] [--audio\|--no-audio] [--dry-run] [rom\|name]` | Launch Mesen locally, or sync/launch on AWS/VNC |
| `play --target aws --vnc-tunnel` | Print `ssh -L 5901:127.0.0.1:5901 …`, then connect to `vnc://127.0.0.1:5901` |
| `configure [--target local\|aws]` | Ansible configure (aws: sshd harden + VNC localhost + PipeWire + SDL2 RPM) |
| `apply [--dry-run] [--init]` | Terraform plan/apply (`enable_aws=false` → local marker only) |
| `up` | Placeholder for a one-shot local bootstrap |

```bash
PYTHONPATH=src python3 -m nes_kickoff <command>
```

### Connect cheat sheet

```bash
ssh -i ~/.ssh/neo-atari.pem -L 5901:127.0.0.1:5901 ec2-user@HOST
```

Then `vnc://127.0.0.1:5901`.

## Keymap

| Keys | NES / GB |
|------|----------|
| W A S D / arrows | D-pad |
| X / Space | A |
| Z | B |
| Enter | Start |
| Shift / Tab | Select |

See `config/keymap.yaml` and `config/mesen_keymap.json`. Apply writes Mapping2 (WASD+X/Z/Enter/Shift) and Mapping3 (arrows+Space/Tab) for `Nes.Port1` and `Gameboy.Controller`.

### `games.yaml` shape

```yaml
games:
  - name: Super Mario Bros
    system: nes
    rom: roms/Super_Mario_Bros.nes
  - name: Tetris
    system: gb
    rom: roms/Tetris.gb
```

`system` is one of `nes`, `gb`, `snes`, `gba`. `play --system` filters to that console; if omitted, the CLI infers from the ROM extension or the matched entry.

## Costs / teardown

- Default AWS shape: `t3.small` + 20 GB gp3 in us-east-2. **Stop or destroy when idle** — idle EC2 still bills.
- Tear down cloud resources: `cd terraform && terraform destroy` (or set `enable_aws=false` and apply carefully).
- Local Mesen/ROMs are unaffected by destroy.
- **SG description is immutable** in AWS — do not casually edit `aws_security_group.mesen` description after first create.

## Never commit

ROMs (`roms/*`), `terraform.tfvars`, Terraform state (`.tfstate*`, `.terraform/`), VNC passwords, generated `ansible/inventory/aws.yml`, PEM keys, or other secrets.
