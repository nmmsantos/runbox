#!/bin/sh

set -eu

exec 3>&1 >&2

# runbox include common

# runbox pre-run-output

if [ "$#" -ne 1 ] || [ -z "${1:-}" ]; then
    printf 'usage: %s <base-dir>\n' "${0##*/}" >&2
    exit 1
fi

BASE_DIR="$1"

mkdir -p "$BASE_DIR"
DEST="$(readlink -f "$BASE_DIR")/linuxdeploy"

if [ ! -d "$DEST" ]; then
    mv -T "$INSTALL_DIR/app" "$DEST"
fi

activate_path "$DEST"
