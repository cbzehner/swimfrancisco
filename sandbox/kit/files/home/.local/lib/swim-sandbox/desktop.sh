#!/usr/bin/env bash
set -euo pipefail
exec 9>/tmp/swim-desktop.lock
flock -n 9 || exit 0
trap 'kill $(jobs -pr) 2>/dev/null || true' EXIT
trap 'exit 0' TERM INT
unset WAYLAND_DISPLAY
export XDG_SESSION_TYPE=x11

# A stopped VM can leave X11's PID file and socket behind.
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99
Xvfb :99 -screen 0 1440x900x24 -nolisten tcp > /tmp/swim-xvfb.log 2>&1 &
for attempt in {1..50}; do
  [[ -S /tmp/.X11-unix/X99 ]] && break
  sleep 0.1
done
openbox > /tmp/swim-openbox.log 2>&1 &
x11vnc -display :99 -localhost -nopw -forever -shared -rfbport 5900 \
  > /tmp/swim-vnc.log 2>&1 &
websockify --web=/usr/share/novnc 0.0.0.0:6080 127.0.0.1:5900 \
  > /tmp/swim-websockify.log 2>&1 &
until [[ -f /home/agent/.swim-sandbox-ready ]]; do sleep 1; done
browser_trust_store="${XDG_DATA_HOME:-$HOME/.local/share}/pki/nssdb"
mkdir -p "$browser_trust_store"
if [[ ! -f "$browser_trust_store/cert9.db" ]]; then
  certutil -N -d "sql:$browser_trust_store" --empty-password
fi
certutil -D -d "sql:$browser_trust_store" -n swim-sandbox-proxy 2>/dev/null || true
certutil -A -d "sql:$browser_trust_store" -n swim-sandbox-proxy -t 'C,,' \
  -i /usr/local/share/ca-certificates/proxy-ca.crt
cd /home/agent/workspace
/home/agent/.local/lib/swim-sandbox/node-package/bin/node \
  /home/agent/.local/lib/swim-sandbox/browser.cjs \
  > /tmp/swim-browser.log 2>&1 &
wait
