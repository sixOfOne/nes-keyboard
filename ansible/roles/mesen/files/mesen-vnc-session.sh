#!/bin/bash
# Minimal X session for TigerVNC: metacity WM + an xterm for launching Mesen.
set -euo pipefail
unset SESSION_MANAGER
export XDG_SESSION_TYPE="${XDG_SESSION_TYPE:-x11}"

uid=$(id -u)
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/${uid}}"
# Prefer the systemd user bus so PipeWire (a user service) is the same
# server SSH launches talk to. dbus-launch would start a private bus.
if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] && [ -S "${XDG_RUNTIME_DIR}/bus" ]; then
  export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
elif [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] && command -v dbus-launch >/dev/null 2>&1; then
  eval "$(dbus-launch --sh-syntax)"
fi

if [ -x /usr/local/bin/mesen-audio-setup ]; then
  /usr/local/bin/mesen-audio-setup \
    || echo "mesen-vnc-session: audio sink not ready (Mesen will stay silent)" >&2
fi

if command -v xrdb >/dev/null 2>&1 && [ -r "$HOME/.Xresources" ]; then
  xrdb -merge "$HOME/.Xresources"
fi

if command -v xsetroot >/dev/null 2>&1; then
  xsetroot -solid '#2e3436' || true
fi

metacity --sm-disable &
sleep 0.5
exec xterm -geometry 100x30+40+40 -fa DejaVuSansMono -fs 11 -ls \
  -T "Mesen VNC — mesen-flatpak ~/roms/Super_Mario_Bros.nes"
