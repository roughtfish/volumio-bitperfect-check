#!/bin/bash
# Installs or updates the Volumio now-playing page.
#
# Run this on your Volumio device (over SSH), as the normal volumio user:
#   curl -fsSL https://raw.githubusercontent.com/roughtfish/volumio-bitperfect-check/main/nowplaying/install.sh | bash
#
# Running it again updates to the latest version and keeps your settings.

set -e

REPO_RAW="${NOWPLAYING_REPO:-https://raw.githubusercontent.com/roughtfish/volumio-bitperfect-check/main/nowplaying}"
DIR="$HOME/nowplaying"
SERVICE=/etc/systemd/system/nowplaying.service
PORT=8080

say()  { printf '\n\033[1m%s\033[0m\n' "$1"; }
fail() { printf '\n\033[31mError: %s\033[0m\n' "$1" >&2; exit 1; }

if [ "$(id -u)" -eq 0 ]; then
    fail "Run this as your normal user (for example 'volumio'), not with sudo. It will ask for your password when it needs it."
fi

command -v python3 >/dev/null 2>&1 || fail "python3 was not found on this device."
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 7) else 1)' \
    || fail "Python 3.7 or newer is needed (found $(python3 --version 2>&1))."

if command -v curl >/dev/null 2>&1; then
    download() { curl -fsSL "$1" -o "$2"; }
elif command -v wget >/dev/null 2>&1; then
    download() { wget -q "$1" -O "$2"; }
else
    fail "Neither curl nor wget is available."
fi

say "Downloading the now-playing page to $DIR"
mkdir -p "$DIR"
for f in nowplaying.py config.example.json; do
    download "$REPO_RAW/$f" "$DIR/$f.new" || fail "Could not download $f."
    mv -f "$DIR/$f.new" "$DIR/$f"
    echo "  $f"
done

if [ -f "$DIR/config.json" ]; then
    echo "  Keeping your existing config.json"
else
    cp "$DIR/config.example.json" "$DIR/config.json"
    echo "  Created config.json (fill it in from the settings page)"
fi

say "Setting up the service (your password may be needed)"
sudo tee "$SERVICE" >/dev/null <<EOF
[Unit]
Description=Volumio now-playing page
After=network-online.target volumio.service

[Service]
ExecStart=$(command -v python3) $DIR/nowplaying.py
Restart=always
RestartSec=5
User=$(id -un)

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable nowplaying >/dev/null 2>&1
sudo systemctl restart nowplaying

sleep 2
if ! systemctl is-active --quiet nowplaying; then
    fail "The service didn't start. See: journalctl -u nowplaying -n 30 --no-pager"
fi

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -n "$IP" ] || IP=$(hostname)

VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$DIR/nowplaying.py" | head -1)

say "Done! Installed version ${VERSION:-unknown}"
echo "  Now-playing page:  http://$IP:$PORT"
echo "  Settings:          http://$IP:$PORT/settings"
echo
echo "Open the settings page to add your Discogs and Last.fm details."
echo "Run this installer again at any time to update. Your settings are kept."
