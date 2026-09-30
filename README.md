# nes-keyboard

Keyboard-controlled NES play via [Mesen](https://github.com/nesdev-org/MesenCE) (MesenCE), with a Python kickoff CLI, Ansible for host config, and Terraform for an optional AWS EC2 host.

Modeled on `atari-keyboard` (Stella / Pac-Man). Emulator rename: Stella → **Mesen**; ROM: Super Mario Bros (`.nes`).

## Status (scaffold)

- **Local (macOS):** project layout, `nes_kickoff` CLI (`play` / `configure` / `apply`), ROM under `roms/` (gitignored), WASD/arrows/A/B/Start/Select keymap **stub**, smoke test.
- **Mesen install:** `/Applications/Mesen.app` is present (arm64); `mesen` is not yet on PATH — symlink via configure or `ln -sfn … ~/.local/bin/mesen`. Smoke test finds the app bundle. Keymap apply remains stubbed until settings format is confirmed.
- **AWS:** Terraform local-ready (`enable_aws=false` by default). Same shape as atari-keyboard: us-east-2, cheap `t3.small`, VNC on 127.0.0.1 via SSH tunnel only, sshd hardening, PipeWire remote audio. Reuses **`neo-atari`** key pair + `~/.ssh/neo-atari.pem` unless you create a dedicated NES key later.
- **Do not** `terraform apply` / spend AWS money until you intentionally flip `enable_aws` and review tfvars. **Do not** push to GitHub unless asked.

## Layout

```
config/           keymap intent + mesen_keymap.json stub + games.yaml
roms/             local ROMs only (gitignored; keep .gitkeep)
scripts/          smoke_test, apply_mesen_keymap (stub), render_aws_inventory
src/nes_kickoff   CLI entrypoint
ansible/          localhost + aws inventories, sshd + mesen roles
terraform/        local marker by default; EC2 when enable_aws=true
```

## Local quick start

1. Install Mesen (macOS build from [MesenCE releases](https://github.com/nesdev-org/MesenCE/releases)). Symlink when ready:
   `ln -sfn /Applications/Mesen.app/Contents/MacOS/Mesen ~/.local/bin/mesen`
   (or `MesenCE.app` if that is the bundle name).
2. ROM is already at `roms/Super_Mario_Bros.nes` and listed in `config/games.yaml` (gitignored).
3. Keymap stub (safe before Mesen lands):
   `python3 scripts/apply_mesen_keymap.py`
4. Smoke check (ROM required; Mesen optional until installed):
   `python3 scripts/smoke_test.py`
5. Play (after Mesen is installed):
   `PYTHONPATH=src python3 -m nes_kickoff play`
   (uses `open -a Mesen` on macOS when the app bundle exists)

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
PYTHONPATH=src python3 -m nes_kickoff play "Super Mario Bros" --target aws
```

### Remote audio

TigerVNC is picture + keyboard only. `configure --target aws` installs PipeWire and a null sink named `mesen`. `play --target aws` streams raw PCM over SSH into local `sox play` / `ffmpeg` / `ffplay`. Leave that Terminal open for sound. Log: `~/.cache/nes-kickoff/vnc-audio.log`.

## CLI cheat sheet

| Command | Purpose |
|--------|---------|
| `play [--target local\|aws] [--audio\|--no-audio] [--dry-run] [rom\|name]` | Launch Mesen locally, or sync/launch on AWS/VNC |
| `play --target aws --vnc-tunnel` | Print SSH local-forward for `vnc://127.0.0.1:5901` |
| `configure [--target local\|aws]` | Ansible configure (aws: sshd harden + VNC localhost + PipeWire) |
| `apply [--dry-run] [--init]` | Terraform plan/apply (`enable_aws=false` → local marker only) |
| `up` | Placeholder for a one-shot local bootstrap |

```bash
PYTHONPATH=src python3 -m nes_kickoff <command>
```

## Keymap (intent)

| Keys | NES |
|------|-----|
| W A S D / arrows | D-pad |
| X / Space | A (jump) |
| Z | B (run) |
| Enter | Start |
| Shift / Tab | Select |

See `config/keymap.yaml` and `config/mesen_keymap.json`. Apply script is stubbed until Mesen settings format is confirmed for the installed build.

## Costs / teardown

- Default AWS shape: `t3.small` + 8 GB gp3 in us-east-2. Stop or destroy when idle.
- Tear down: `cd terraform && terraform destroy` (or set `enable_aws=false` and apply carefully).
- Local Mesen/ROMs are unaffected by destroy.
- **SG description is immutable** in AWS — do not casually edit `aws_security_group.mesen` description after first create.

## Never commit

ROMs, `terraform.tfvars`, Terraform state, VNC passwords, generated `ansible/inventory/aws.yml`, AWS inventory secrets.
