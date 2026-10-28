#!/bin/sh

set -eu

ME="$(readlink -f "$0")"
MY_DIR="$(dirname "$ME")"

if [ ! -x "$MY_DIR/linuxdeploy" ] || [ ! -x "$MY_DIR/patchelf" ]; then
    # https://github.com/linuxdeploy/linuxdeploy
    curl -fL "https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage" \
        -o "$MY_DIR/linuxdeploy-x86_64.AppImage"

    chmod +x "$MY_DIR/linuxdeploy-x86_64.AppImage"

    (cd "$MY_DIR" && ./linuxdeploy-x86_64.AppImage --appimage-extract)

    mv -t "$MY_DIR" \
        "$MY_DIR/squashfs-root/usr/bin/linuxdeploy" \
        "$MY_DIR/squashfs-root/usr/bin/patchelf"

    rm -rf \
        "$MY_DIR/linuxdeploy-x86_64.AppImage" \
        "$MY_DIR/squashfs-root"
fi
