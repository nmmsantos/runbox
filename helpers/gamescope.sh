#!/bin/sh

set -eu

exec 3>&1 >&2

if [ "$#" -lt 1 ] || [ -z "${1:-}" ]; then
    printf 'usage: %s <destination> [gamescope arguments...]\n' "${0##*/}" >&2
    exit 1
fi

DEST="$1"
shift

mkdir -p "$DEST/bin"
DEST="$(readlink -f "$DEST")"

QUOTED_DEST="$(printf "'"; printf '%s' "$DEST" | sed "s/'/'\\\\''/g"; printf "'")"

GAMESCOPE_ARGS=

for ARG in "$@"; do
    QUOTED_ARG="$(printf "'"; printf '%s' "$ARG" | sed "s/'/'\\\\''/g"; printf "'")"
    GAMESCOPE_ARGS="${GAMESCOPE_ARGS:+$GAMESCOPE_ARGS }$QUOTED_ARG"
done

tee "$DEST/bin/gs" >/dev/null <<EOF
#!/bin/sh

set -eu

if [ "\${GAMESCOPE_SESSION:-}" != 1 ]; then
    unset DISPLAY WAYLAND_DISPLAY SEATD_SOCK

    export GAMESCOPE_SESSION=1
    export LIBSEAT_BACKEND=seatd
    export SEATD_VTBOUND=1

    exec sudo -E openvt -s -w -- seatd-launch -- "\$0" "\$@"
fi

chown "\$MY_USER:" "\$SEATD_SOCK"

exec setpriv \\
    --reuid "\$MY_USER" \\
    --regid "\$MY_USER" \\
    --init-groups \\
    --inh-caps +sys_nice \\
    --ambient-caps +sys_nice \\
    gamescope \\
        --backend drm \\
        $GAMESCOPE_ARGS \\
        -- \\
        "\$@"
EOF

chmod 0755 "$DEST/bin/gs"

tee /dev/fd/3 >/dev/null <<EOF
case ":\$PATH:" in
    *:$QUOTED_DEST/bin:*) ;;
    *) PATH=$QUOTED_DEST/bin:"\$PATH" ;;
esac

export PATH
EOF
