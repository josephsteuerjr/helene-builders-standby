#!/bin/sh
set -eu
target=$1
if [ "$target" = debian ]; then
  apt-get -qq update
  DEBIAN_FRONTEND=noninteractive apt-get -qq install -y python3 git xvfb xauth dbus-x11 imagemagick libxcb-shape0 libxfixes3 libfontconfig1 libegl1 libopengl0 libnss3 libasound2 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0 libxcb-xkb1 libxkbcommon-x11-0 libdbus-1-3 libxdamage1 libxcomposite1 libxrandr2 libgbm1 libgl1 openbox wmctrl xdotool x11-utils libxtst6 libatspi2.0-0 at-spi2-core xclip fonts-dejavu-core
else
  dnf -qy install python3 git-core xorg-x11-server-Xvfb xorg-x11-xauth dbus-x11 ImageMagick libXfixes fontconfig mesa-libEGL libglvnd-opengl nss alsa-lib xcb-util-cursor xcb-util-wm xcb-util-image xcb-util-keysyms xcb-util-renderutil libxcb libxkbcommon-x11 dbus-libs libXdamage libXcomposite libXrandr mesa-libgbm openbox wmctrl xdotool /usr/bin/xprop /usr/bin/xdpyinfo /usr/bin/xwininfo libXtst at-spi2-core xclip dejavu-sans-fonts shadow-utils util-linux
fi
useradd -m heleneqa
chown -R heleneqa /stand
cd /stand
runuser -u heleneqa -- python3 ui_prepare.py "$target"
Xvfb :99 -screen 0 1360x900x24 -nolisten tcp -ac >/tmp/screen.log 2>&1 &
export DISPLAY=:99
for count in $(seq 1 40); do xdpyinfo >/dev/null 2>&1 && break; sleep .2; done
runuser -u heleneqa -- env HOME=/home/heleneqa DISPLAY=:99 QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu dbus-run-session -- sh -ec '
  openbox --sm-disable >/tmp/heleneqa-wm.log 2>&1 &
  for count in $(seq 1 100); do wmctrl -m 2>/dev/null | grep -q Openbox && break; sleep .1; done
  wmctrl -m
  exec desktop/runtime/bin/python3 -Bu ui_stand.py "$1"
' sh "$target"
