#!/bin/sh

set -eu

exec 3>&1 >&2

if [ "$#" -ne 2 ] || [ -z "${1:-}" ] || [ -z "${2:-}" ]; then
    printf 'usage: %s <base-dir> <version>\n' "${0##*/}" >&2
    exit 1
fi

BASE_DIR="$1"
VERSION="$2"

mkdir -p "$BASE_DIR"
DEST="$(readlink -f "$BASE_DIR")/javafx-${VERSION}"

if [ ! -d "$DEST" ]; then
    INSTALL_DIR="$(mktemp -d)"

    # https://gluonhq.com/products/javafx
    curl -fL "https://download2.gluonhq.com/openjfx/${VERSION}/openjfx-${VERSION}_linux-x64_bin-sdk.zip" -o "$INSTALL_DIR/javafx.zip"
    unzip -q "$INSTALL_DIR/javafx.zip" -d "$INSTALL_DIR"

    test -f "$INSTALL_DIR/javafx-sdk-${VERSION}/lib/javafx.controls.jar"

    mv -T "$INSTALL_DIR/javafx-sdk-${VERSION}" "$DEST"
fi

QUOTED_DEST="$(printf "'"; printf '%s' "$DEST" | sed "s/'/'\\\\''/g"; printf "'")"

tee /dev/fd/3 >/dev/null <<SH
export JAVAFX_HOME=$QUOTED_DEST
SH
