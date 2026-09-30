# nes-keyboard

Keyboard-controlled NES / Game Boy play via [Mesen](https://github.com/nesdev-org/MesenCE) (MesenCE), with a Python kickoff CLI, Ansible for host config, and Terraform for an optional AWS EC2 host.

Modeled on `atari-keyboard` (Stella / Pac-Man). Emulator: **MesenCE** (NES/SNES/GB/GBA). Bundled games: Super Mario Bros (`.nes`) and Tetris (`.gb`).

## Status (scaffold)

- **Local (macOS):** project layout, `nes_kickoff` CLI (`play` / `configure` / `apply`), ROMs under `roms/` (gitignored), WASD/arrows/A/B/Start/Select keymap applied into MesenCE `settings.json` for **NES Port1** and **Game Boy Controller**, smoke test.
- **Mesen install:** `/Applications/Mesen.app` (arm64 MesenCE 2.2.1) + `~/.local/bin/mesen` symlink. Keymap writes `~/Library/Application Support/MesenCE/settings.json` (`Nes.Port1` + `Gameboy.Controller` Mapping2/Mapping3 Avalonia key codes).
- **AWS:** Terraform local-ready (`enable_aws=false` by default). Same shape as atari-keyboard: us-east-2, cheap `t3.small`, VNC on 127.0.0.1 via SSH tunnel only, sshd hardening, PipeWire remote audio. Reuses **`neo-atari`** key pair + `~/.ssh/neo-atari.pem` unless you create a dedicated NES key later.
- **Do not** `terraform apply` / spend AWS money until you intentionally flip `enable_aws` and review tfvars. **Do not** push to GitHub unless asked.

## Layout

```
config/           keymap intent + mesen_keymap.json stub + games.yaml
roms/             local ROMs only (gitignored; keep .gitkeep)
scripts/          smoke_test, apply_mesen_keymap, render_aws_inventory
src/nes_kickoff   CLI entrypoint
ansible/          localhost + aws inventories, sshd + mesen roles
terraform/        local marker by default; EC2 when enable_aws=true
```

## Local quick start

1. Install Mesen (macOS build from [MesenCE releases](https://github.com/nesdev-org/MesenCE/releases)). Symlink when ready:
   `ln -sfn /Applications/Mesen.app/Contents/MacOS/Mesen ~/.local/bin/mesen`
   (or `MesenCE.app` if that is the bundle name).
2. ROMs: `roms/Super_Mario_Bros.nes` (NES) and `roms/Tetris.gb` (Game Boy), listed in `config/games.yaml` (gitignored).
3. Apply keymap (quit Mesen first if it is open) — writes NES + Game Boy maps:
   `python3 scripts/apply_mesen_keymap.py`
4. Smoke check (ROM required; Mesen optional until installed):
   `python3 scripts/smoke_test.py`
5. Play (after Mesen is installed):
   ```bash
   PYTHONPATH=src python3 -m nes_kickoff play --system nes "Super Mario Bros"
   PYTHONPATH=src python3 -m nes_kickoff play --system gb Tetris
   ```
   (uses `open -a Mesen` on macOS when the app bundle exists; omit `--system` to infer from the ROM / games.yaml)

Optional local Ansible (symlink + keymap stub):

`PYTHONPATH=src python3 -m nes_kickoff configure --target local`

### Flatpak note (Linux / AWS)

There is **no official Mesen on Flathub**. Community builds exist (e.g. Flatpak id placeholder `ca.mesen.Mesen2` from joshas/Mesen2-flatpak). On Amazon Linux prefer a GitHub release binary or AppImage linked as `/usr/local/bin/mesen`. The `mesen-flatpak` wrapper tries that binary first.

## AWS path (optional; not applied in scaffold)

1. Copy `terraform/terraform.tfvars.example` → `terraform/terraform.tfvars` (gitignored).
2. Set `enable_aws=true`, `aws_region=us-east-2`, `key_name=neo-atari` (reuse), and `ssh_ingress_cidr` (your `/32`). VNC is **not** a security-group port.
3. Keep the private key at `~/.ssh/neo-atari.pem` mode `600` — never in the repo.
4. Credentials via `~/.aws/credentials`.
5. When ready (costs money):

```bash
PYTHONPATH=src python3 -m nes_kickoff apply --dry-run
PYTHONPATH=src python3 -m nes_kickoff apply
PYTHONPATH=src python3 -m nes_kickoff configure --target aws
ssh -i ~/.ssh/neo-atari.pem ec2-user@$(cd terraform && terraform output -raw public_ip)
```

`configure --target aws` installs `/etc/ssh/sshd_config.d/00-nes-keyboard-hardening.conf` and reloads sshd only after `sshd -t` / `sshd -T` accept it (`PasswordAuthentication no`, `KbdInteractiveAuthentication no`, `PermitRootLogin no`, `PubkeyAuthentication yes`). Confirm `.pem` login works before that reload.

### Remote desktop (VNC via SSH tunnel)

Security group: SSH only. TigerVNC listens on **127.0.0.1:5901**.

1. Password file on the Mac (create once; never commit):

```bash
mkdir -p ~/.config/nes-kickoff
openssl rand -base64 6 | tr -d '/+=' | head -c 8 > ~/.config/nes-kickoff/vnc-password.txt
chmod 600 ~/.config/nes-kickoff/vnc-password.txt
```

2. Apply + configure, then tunnel:

```bash
ssh -i ~/.ssh/neo-atari.pem -L 5901:127.0.0.1:5901 ec2-user@HOST
# then: vnc://127.0.0.1:5901
```

`HOST` is `cd terraform && terraform output -raw public_ip`. Same command is printed by `play --target aws` and `play --target aws --vnc-tunnel`.

3. Remote play from the Mac:

```bash
PYTHONPATH=src python3 -m nes_kickoff play --target aws --dry-run
PYTHONPATH=src python3 -m nes_kickoff play --system nes "Super Mario Bros" --target aws
PYTHONPATH=src python3 -m nes_kickoff play --system gb Tetris --target aws
```

### Remote audio

TigerVNC is picture + keyboard only. `configure --target aws` installs PipeWire and a null sink named `mesen`. `play --target aws` streams raw PCM over SSH into local `sox play` / `ffmpeg` / `ffplay`. Leave that Terminal open for sound. Log: `~/.cache/nes-kickoff/vnc-audio.log`.

## CLI cheat sheet

| Command | Purpose |
|--------|---------|
| `play [--system nes\|gb\|snes\|gba] [--target local\|aws] [--audio\|--no-audio] [--dry-run] [rom\|name]` | Launch Mesen locally, or sync/launch chosen ROM on AWS/VNC |
| `play --target aws --vnc-tunnel` | Print SSH local-forward for `vnc://127.0.0.1:5901` |
| `configure [--target local\|aws]` | Ansible configure (aws: sshd harden + VNC localhost + PipeWire) |
| `apply [--dry-run] [--init]` | Terraform plan/apply (`enable_aws=false` → local marker only) |
| `up` | Placeholder for a one-shot local bootstrap |

```bash
PYTHONPATH=src python3 -m nes_kickoff <command>
```

## Keymap (intent)

Same WASD feel for NES and Game Boy:

| Keys | NES / GB |
|------|----------|
| W A S D / arrows | D-pad |
| X / Space | A |
| Z | B |
| Enter | Start |
| Shift / Tab | Select |

See `config/keymap.yaml` and `config/mesen_keymap.json`. Apply writes Avalonia key codes into `Nes.Port1` and `Gameboy.Controller` Mapping2 (WASD+X/Z/Enter/Shift) and Mapping3 (arrows+Space/Tab) in `~/Library/Application Support/MesenCE/settings.json` (Linux: `~/.config/MesenCE/settings.json`).

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

`system` is one of `nes`, `gb`, `snes`, `gba`. `play --system` filters to that console; if omitted, the CLI infers from the ROM extension or the matched games.yaml entry.

## Costs / teardown

- Default AWS shape: `t3.small` + 20 GB gp3 in us-east-2. Stop or destroy when idle.
- Tear down: `cd terraform && terraform destroy` (or set `enable_aws=false` and apply carefully).
- Local Mesen/ROMs are unaffected by destroy.
- **SG description is immutable** in AWS — do not casually edit `aws_security_group.mesen` description after first create.

## Never commit

ROMs, `terraform.tfvars`, Terraform state, VNC passwords, generated `ansible/inventory/aws.yml`, AWS inventory secrets.
