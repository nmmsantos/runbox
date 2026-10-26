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
DEST="$(readlink -f "$BASE_DIR")/java-temurin-${VERSION}"

if [ ! -d "$DEST" ]; then
    INSTALL_DIR="$(mktemp -d)"

    mkdir -p "$INSTALL_DIR/app"

    # https://adoptium.net/temurin/releases
    curl -fL "https://api.adoptium.net/v3/binary/version/jdk-${VERSION}/linux/x64/jdk/hotspot/normal/eclipse" \
    | tar xzC "$INSTALL_DIR/app" --no-same-owner --strip-components 1

    test -x "$INSTALL_DIR/app/bin/java"
    test -x "$INSTALL_DIR/app/bin/javac"

    mv -T "$INSTALL_DIR/app" "$DEST"
fi

activate_export JAVA_HOME "$DEST"
activate_path "$DEST/bin"
