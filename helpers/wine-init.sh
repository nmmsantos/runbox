#!/bin/sh

set -eu

: "${WINEPREFIX:?WINEPREFIX must be provided by the calling script}"
: "${WINEARCH:?WINEARCH must be provided by the calling script}"

if [ ! -d "$WINEPREFIX" ] || [ -e "$WINEPREFIX/dosdevices/z:" ]; then
    WINEDLLOVERRIDES="mscoree,mshtml=d" winetricks sandbox
fi
