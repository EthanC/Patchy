#!/bin/sh
# Run Patchy as PUID:PGID (default 1000:1000) so files in /data are owned by the
# host user. When the container is already started as a non-root user, run as-is.
set -eu

if [ "$(id -u)" != "0" ]; then
    exec "$@"
fi

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

case "${PUID}${PGID}" in
    *[!0-9]*|"")
        echo "PUID and PGID must be numeric (got PUID=${PUID}, PGID=${PGID})" >&2
        exit 1
        ;;
esac

if ! getent group "${PGID}" > /dev/null; then
    addgroup -g "${PGID}" patchy
fi

if ! getent passwd "${PUID}" > /dev/null; then
    adduser -D -H -h /data -s /sbin/nologin -u "${PUID}" \
        -G "$(getent group "${PGID}" | cut -d: -f1)" patchy
fi

# Only Patchy's own files are re-owned, never the rest of a mounted volume.
chown "${PUID}:${PGID}" /data
find /data -maxdepth 1 -name 'patchy.db*' -exec chown "${PUID}:${PGID}" {} +

export HOME=/data

exec su-exec "${PUID}:${PGID}" "$@"
