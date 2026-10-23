#!/bin/sh

set -eu

exec 3>&1 >&2

if [ "$#" -ne 4 ] || [ -z "${1:-}" ] || [ -z "${2:-}" ] || [ -z "${3:-}" ] || [ -z "${4:-}" ]; then
    printf 'usage: %s <base-dir> <publisher> <flavor> <version>\n' "${0##*/}" >&2
    exit 1
fi

BASE_DIR="$1"
PUBLISHER="$2"
FLAVOR="$3"
VERSION="$4"

mkdir -p "$BASE_DIR"
DEST="$(readlink -f "$BASE_DIR")/wine-${PUBLISHER}-${FLAVOR}-${VERSION}"

if [ ! -d "$DEST" ]; then
    INSTALL_DIR="$(mktemp -d)"

    mkdir -p "$INSTALL_DIR/app"

    case "$PUBLISHER" in
        kron4ek)
            # https://github.com/Kron4ek/Wine-Builds/releases
            curl -fL "https://github.com/Kron4ek/Wine-Builds/releases/download/${VERSION}/wine-${VERSION}-${FLAVOR}.tar.xz" \
            | tar xJC "$INSTALL_DIR/app" --no-same-owner --strip-components 1
            ;;
        proton-ge)
            # https://github.com/GloriousEggroll/proton-ge-custom/releases
            curl -fL "https://github.com/GloriousEggroll/proton-ge-custom/releases/download/GE-Proton${VERSION}/GE-Proton${VERSION}-${FLAVOR}.tar.gz" \
            | tar xzC "$INSTALL_DIR/app" --no-same-owner --strip-components 2 --wildcards '*/files'
            ;;
        *)
            printf 'unknown wine publisher: %s\n' "$PUBLISHER" >&2
            exit 1
            ;;
    esac

    # https://github.com/Winetricks/winetricks/releases
    curl -fL 'https://raw.githubusercontent.com/Winetricks/winetricks/master/src/winetricks' \
        -o "$INSTALL_DIR/app/bin/winetricks"

    chmod 0755 "$INSTALL_DIR/app/bin/winetricks"

    test -x "$INSTALL_DIR/app/bin/wine"

    mv -T "$INSTALL_DIR/app" "$DEST"
fi

QUOTED_DEST="$(printf "'"; printf '%s' "$DEST" | sed "s/'/'\\\\''/g"; printf "'")"

tee /dev/fd/3 >/dev/null <<SH
case ":\$PATH:" in
    *:$QUOTED_DEST/bin:*) ;;
    *) PATH=$QUOTED_DEST/bin:"\$PATH" ;;
esac

export PATH
SH
