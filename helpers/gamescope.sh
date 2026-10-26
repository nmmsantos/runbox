#!/bin/sh

set -eu

exec 3>&1 >&2

# runbox include common

if [ "$#" -lt 1 ] || [ -z "${1:-}" ]; then
    printf 'usage: %s <base-dir> [gamescope arguments...]\n' "${0##*/}" >&2
    exit 1
fi

BASE_DIR="$1"
shift

mkdir -p "$BASE_DIR/bin"
DEST="$(readlink -f "$BASE_DIR")/bin"

GAMESCOPE_ARGS=

for ARG in "$@"; do
    QUOTED_ARG="$(shell_quote "$ARG")"
    GAMESCOPE_ARGS="${GAMESCOPE_ARGS:+$GAMESCOPE_ARGS }$QUOTED_ARG"
done

print_wrapper() {
cat <<SH
#!/bin/sh

set -eu

if [ "\${GAMESCOPE_SESSION:-}" != 1 ]; then
    unset DISPLAY WAYLAND_DISPLAY SEATD_SOCK

    export GAMESCOPE_SESSION=1
    export LIBSEAT_BACKEND=seatd
    export SEATD_VTBOUND=1

    exec sudo -E openvt -s -w -- seatd-launch -- "\$0" "\$@"
fi

chown "\$RUNBOX_USER:" "\$SEATD_SOCK"

exec setpriv \\
    --reuid "\$RUNBOX_USER" \\
    --regid "\$RUNBOX_USER" \\
    --init-groups \\
    --inh-caps +sys_nice \\
    --ambient-caps +sys_nice \\
    gamescope \\
        --backend drm \\
        $GAMESCOPE_ARGS \\
        -- \\
        "\$@"
SH
}

print_wrapper >"$DEST/gs"

chmod 0755 "$DEST/gs"

activate_path "$DEST"
