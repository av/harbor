#!/usr/bin/env bash
set -euo pipefail

cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/tauri"
launcher="$cache_dir/AppRun-$(uname -m)"
mkdir -p "$cache_dir"
if [ ! -f "$launcher" ]; then
  curl -fL "https://github.com/tauri-apps/binary-releases/releases/download/apprun-old/$(basename "$launcher")" -o "$launcher.download"
  mv "$launcher.download" "$launcher"
fi
chmod 755 "$launcher"
