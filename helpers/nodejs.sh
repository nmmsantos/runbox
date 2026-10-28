#!/bin/sh

set -eu

exec 3>&1 >&2

# runbox include common

if [ "$#" -ne 2 ] || [ -z "${1:-}" ] || [ -z "${2:-}" ]; then
    printf 'usage: %s <base-dir> <version-without-v-prefix>\n' "${0##*/}" >&2
    exit 1
fi

BASE_DIR="$1"
VERSION="$2"

mkdir -p "$BASE_DIR"
DEST="$(readlink -f "$BASE_DIR")/nodejs-${VERSION}"

if [ ! -d "$DEST" ]; then
    INSTALL_DIR="$(mktemp -d)"

    mkdir -p "$INSTALL_DIR/app"

    # https://nodejs.org/en/download
    curl -fL "https://nodejs.org/dist/v${VERSION}/node-v${VERSION}-linux-x64.tar.xz" \
    | tar xJC "$INSTALL_DIR/app" --no-same-owner --strip-components 1

    test -x "$INSTALL_DIR/app/bin/node"
    test -x "$INSTALL_DIR/app/bin/npm"
    test -x "$INSTALL_DIR/app/bin/npx"

    mv -T "$INSTALL_DIR/app" "$DEST"
fi

activate_path "$DEST/bin"
