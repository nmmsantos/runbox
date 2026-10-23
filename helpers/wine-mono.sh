#!/bin/sh

set -eu

if [ "$#" -ne 1 ] || [ -z "${1:-}" ]; then
    printf 'usage: %s <version>\n' "${0##*/}" >&2
    exit 1
fi

VERSION="$1"

: "${WINEPREFIX:?WINEPREFIX must be provided by the calling script}"
: "${WINEARCH:?WINEARCH must be provided by the calling script}"

case "$WINEARCH" in
    win32|win64)
        ARCH=x86
        ;;
    *)
        printf 'unknown WINEARCH: %s\n' "$WINEARCH" >&2
        exit 1
        ;;
esac

if [ ! -d "$WINEPREFIX/drive_c/windows/mono" ]; then
    # https://dl.winehq.org/wine/wine-mono
    curl -fL "https://dl.winehq.org/wine/wine-mono/${VERSION}/wine-mono-${VERSION}-${ARCH}.msi" -o "$WINEPREFIX/drive_c/mono.msi"

    wine msiexec /i 'C:\mono.msi' /q

    rm "$WINEPREFIX/drive_c/mono.msi"
fi
