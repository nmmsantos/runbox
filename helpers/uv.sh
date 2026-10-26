#!/bin/sh

set -eu

exec 3>&1 >&2

# runbox include common

if [ "$#" -ne 2 ] || [ -z "${1:-}" ] || [ -z "${2:-}" ]; then
    printf 'usage: %s <base-dir> <version>\n' "${0##*/}" >&2
    exit 1
fi

BASE_DIR="$1"
VERSION="$2"

mkdir -p "$BASE_DIR"
DEST="$(readlink -f "$BASE_DIR")/uv-${VERSION}"

if [ ! -d "$DEST" ]; then
    INSTALL_DIR="$(mktemp -d)"

    mkdir -p "$INSTALL_DIR/app"

    # https://github.com/astral-sh/uv/releases
    curl -fL "https://github.com/astral-sh/uv/releases/download/${VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz" \
    | tar xzC "$INSTALL_DIR/app" --no-same-owner --strip-components 1

    test -x "$INSTALL_DIR/app/uv"

    mv -T "$INSTALL_DIR/app" "$DEST"
fi

activate_path "$DEST"
