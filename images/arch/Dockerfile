FROM archlinux:latest AS base

FROM base AS build

RUN set -eu \
    && pacman -Syu --noconfirm base-devel git \
    && useradd -m builder \
    && printf 'builder ALL=(ALL:ALL) NOPASSWD: ALL\n' >/etc/sudoers.d/99-nopasswd \
    && sudo -u builder sh -euc ' \
        cd /tmp \
        && git clone https://aur.archlinux.org/paru-git.git \
        && cd paru-git \
        && sed -i "/^sha256sums=/a options=('\''!debug'\'')" PKGBUILD \
        && makepkg -s --noconfirm \
    ' \
    && mv /tmp/paru-git/paru-git-*.pkg.tar.zst /paru-git.pkg.tar.zst

FROM base

ARG my_gid
ARG my_uid
ARG my_user
ARG xdg_runtime_dir

ARG audio_gid
ARG input_gid
ARG render_gid
ARG video_gid

ENV MY_USER="$my_user"
ENV SHELL=/usr/bin/bash
ENV XDG_RUNTIME_DIR="$xdg_runtime_dir"

RUN --mount=type=bind,from=build,source=/paru-git.pkg.tar.zst,target=/paru-git.pkg.tar.zst \
    set -eu \
    # =============================================================================
    # pacman
    # =============================================================================
    && sed -i -e '/^NoExtract/!b' -e '/etc\/pacman\.conf/b' -e 'd' /etc/pacman.conf \
    && printf '%s\n' \
        '[multilib]' \
        'Include = /etc/pacman.d/mirrorlist' \
        >>/etc/pacman.conf \
    && pacman -Syu --noconfirm \
        glibc \
        sudo \
    && pacman -U --noconfirm /paru-git.pkg.tar.zst \
    # =============================================================================
    # locale, keyboard, timezone
    # =============================================================================
    && printf '%s\n' \
        'en_US.UTF-8 UTF-8' \
        'pt_PT.UTF-8 UTF-8' \
        >/etc/locale.gen \
    && locale-gen \
    && printf '%s\n' \
        'LANG=en_US.UTF-8' \
        'LANGUAGE=en_US:en' \
        'LC_CTYPE=pt_PT.UTF-8' \
        'LC_NUMERIC=pt_PT.UTF-8' \
        'LC_TIME=pt_PT.UTF-8' \
        'LC_COLLATE=pt_PT.UTF-8' \
        'LC_MONETARY=pt_PT.UTF-8' \
        'LC_MESSAGES=en_US.UTF-8' \
        'LC_PAPER=pt_PT.UTF-8' \
        'LC_NAME=pt_PT.UTF-8' \
        'LC_ADDRESS=pt_PT.UTF-8' \
        'LC_TELEPHONE=pt_PT.UTF-8' \
        'LC_MEASUREMENT=pt_PT.UTF-8' \
        'LC_IDENTIFICATION=pt_PT.UTF-8' \
        >/etc/locale.conf \
    && ln -sfn /usr/share/zoneinfo/Europe/Lisbon /etc/localtime \
    # =============================================================================
    # user
    # =============================================================================
    && groupadd -g "$my_gid" "$MY_USER" \
    && _gaudio="$(getent group "$audio_gid" | cut -d: -f1)" \
    && if [ -z "$_gaudio" ]; then _gaudio=host_audio; groupadd -g "$audio_gid" "$_gaudio"; fi \
    && _ginput="$(getent group "$input_gid" | cut -d: -f1)" \
    && if [ -z "$_ginput" ]; then _ginput=host_input; groupadd -g "$input_gid" "$_ginput"; fi \
    && _grender="$(getent group "$render_gid" | cut -d: -f1)" \
    && if [ -z "$_grender" ]; then _grender=host_render; groupadd -g "$render_gid" "$_grender"; fi \
    && _gvideo="$(getent group "$video_gid" | cut -d: -f1)" \
    && if [ -z "$_gvideo" ]; then _gvideo=host_video; groupadd -g "$video_gid" "$_gvideo"; fi \
    && useradd -g "$my_gid" -G "wheel,$_gaudio,$_ginput,$_grender,$_gvideo" -m -s "$SHELL" -u "$my_uid" "$MY_USER" \
    # =============================================================================
    # sudo
    # =============================================================================
    && printf '%s\n' \
        'Defaults env_keep += "RUNBOX_SCRIPT"' \
        '%wheel ALL=(ALL:ALL) NOPASSWD: ALL' \
        >/etc/sudoers.d/99-nopasswd \
    && chmod 0440 /etc/sudoers.d/99-nopasswd \
    # =============================================================================
    # pacman finish
    # =============================================================================
    && yes | pacman -Scc

USER "$MY_USER"

RUN \
    set -eu \
    # =============================================================================
    # common packages
    # =============================================================================
    && paru -S --noconfirm --needed \
        # shared downloads, archives, and scripting
        7zip \
        curl \
        docker \
        expect \
        git \
        go-yq \
        gomplate-bin \
        jq \
        python \
        ruby-hocon \
        sd \
        unrar \
        unzip \
        zip \
        # build tools for native software
        base-devel \
        cmake \
        ninja \
        patchelf \
        # interactive shell and troubleshooting
        bash-completion \
        bat \
        bind \
        dua-cli \
        fd \
        fzf \
        lsof \
        man-db \
        man-pages \
        nano \
        pkgfile \
        ripgrep \
        rlwrap \
        usbutils \
        zellij \
        zoxide \
        # desktop apps and dialogs
        chromium \
        gnu-free-fonts \
        gtk3 \
        lib32-gtk3 \
        noto-fonts-emoji \
        xcb-util-cursor \
        xcb-util-wm \
        xdg-user-dirs \
        zenity \
        # opengl, vulkan, and video acceleration
        lib32-libglvnd \
        lib32-libva \
        lib32-mesa \
        lib32-vkd3d \
        lib32-vulkan-icd-loader \
        lib32-vulkan-radeon \
        libglvnd \
        libva \
        mesa \
        vkd3d \
        vulkan-icd-loader \
        vulkan-radeon \
        # graphics diagnostics
        lib32-mesa-utils \
        mesa-utils \
        vulkan-tools \
        xorg-xrandr \
        # direct display sessions
        gamescope \
        kbd \
        seatd \
        # audio and media playback
        alsa-lib \
        alsa-plugins \
        ffmpeg \
        gst-plugins-base \
        gst-plugins-good \
        jack2 \
        lib32-alsa-lib \
        lib32-alsa-plugins \
        lib32-jack2 \
        lib32-libpipewire \
        lib32-libpulse \
        lib32-pipewire \
        libpipewire \
        libpulse \
        pipewire \
        # shared runtime libraries
        gnutls \
        lib32-gnutls \
        lib32-libnm \
        lib32-libxcrypt-compat \
        lib32-libxss \
        lib32-nspr \
        lib32-nss \
        lib32-sqlite \
        libnm \
        libxcrypt-compat \
        libxss \
        nspr \
        nss \
        sqlite \
    # && paru -S --noconfirm --needed \
    #     --assume-installed wine \
    #     wine-mono \
    # && paru -S --noconfirm --needed \
    #     --assume-installed NTSYNC-MODULE,ntsync-autoload \
    #     wine \
    && sudo pkgfile --update \
    && printf '%s\n' \
        '' \
        'if [[ -r /usr/share/doc/pkgfile/command-not-found.bash ]]; then' \
        '  . /usr/share/doc/pkgfile/command-not-found.bash' \
        'fi' \
        '' \
        'HISTSIZE=20000' \
        'HISTFILESIZE=200000' \
        'HISTCONTROL=ignoredups:erasedups' \
        'HISTIGNORE=ls:pwd:exit:clear:history' \
        '' \
        'shopt -s histappend' \
        '' \
        'eval "$(fzf --bash)"' \
        'eval "$(zoxide init bash)"' \
        '' \
        "alias cd='z'" \
        | sudo tee -a /etc/bash.bashrc >/dev/null \
    # =============================================================================
    # paru finish
    # =============================================================================
    && yes | paru -Scc \
    # =============================================================================
    # dirs
    # =============================================================================
    && sudo mkdir -p \
        "$XDG_RUNTIME_DIR" \
    && sudo chmod 0700 \
        "$XDG_RUNTIME_DIR" \
    && sudo chown -R "$MY_USER:" \
        "$XDG_RUNTIME_DIR"
