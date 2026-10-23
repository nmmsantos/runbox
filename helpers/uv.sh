#!/bin/sh

set -eu

exec 3>&1 >&2

if [ "$#" -ne 2 ] || [ -z "${1:-}" ] || [ -z "${2:-}" ]; then
    printf 'usage: %s <destination> <version>\n' "${0##*/}" >&2
    exit 1
fi

DEST="$1"
VERSION="$2"

mkdir -p "$(dirname "$DEST")"
DEST="$(readlink -f "$DEST")"

if [ ! -d "$DEST" ]; then
    INSTALL_DIR="$(mktemp -d)"

    mkdir -p "$INSTALL_DIR/app"

    # https://github.com/astral-sh/uv/releases
    curl -fL "https://github.com/astral-sh/uv/releases/download/${VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz" \
    | tar xzC "$INSTALL_DIR/app" --no-same-owner --strip-components 1

    test -x "$INSTALL_DIR/app/uv"

    mv -T "$INSTALL_DIR/app" "$DEST"
fi

QUOTED_DEST="$(printf "'"; printf '%s' "$DEST" | sed "s/'/'\\\\''/g"; printf "'")"

tee /dev/fd/3 >/dev/null <<EOF
case ":\$PATH:" in
    *:$QUOTED_DEST:*) ;;
    *) PATH=$QUOTED_DEST:"\$PATH" ;;
esac

export PATH
EOF
