#!/bin/sh
# Container entrypoint: bring up the virtual display + VNC stack, then run
# whatever CMD was given (the API server by default).
set -eu

mkdir -p "${GRS_PROFILE_DIR:-/config/browser-profile}" "${GRS_OUTPUT_DIR:-/output}"

echo "[entrypoint] starting Xvfb on ${DISPLAY:-:99}"
Xvfb "${DISPLAY:-:99}" -screen 0 1440x900x24 -nolisten tcp &

# Wait for the X socket so Chrome doesn't race it.
i=0
while [ ! -e "/tmp/.X11-unix/X${DISPLAY#:}" ] && [ "$i" -lt 50 ]; do
    i=$((i + 1)); sleep 0.1
done

echo "[entrypoint] starting x11vnc (internal :5900)"
x11vnc -display "${DISPLAY:-:99}" -forever -shared -nopw -quiet -localhost &

echo "[entrypoint] starting noVNC on :6080"
websockify --daemon --web /usr/share/novnc 6080 localhost:5900

echo "[entrypoint] exec: $*"
exec "$@"
