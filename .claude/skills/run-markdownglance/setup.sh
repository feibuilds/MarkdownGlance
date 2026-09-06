#!/usr/bin/env bash
# Assemble a portable Sublime Text 4200 profile that runs this checkout.
#
#   .claude/skills/run-markdownglance/setup.sh [ROOT]
#
# ROOT defaults to $MDGLANCE_ST_ROOT or /tmp/mdglance-st. The user's own
# Sublime Text configuration is never touched: everything lives under ROOT.
# The checkout is linked in as Data/Packages/MarkdownGlance, so an edit in the
# repository is live in the portable instance on its next start; the probe
# package is linked the same way. The two Package Control libraries the
# package declares are installed with pip into Data/Lib/python38, which is
# where Package Control would put them for the Python 3.8 plugin host.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SKILL_DIR/../../.." && pwd)"
ROOT="${1:-${MDGLANCE_ST_ROOT:-/tmp/mdglance-st}}"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/markdownglance"
TARBALL="$CACHE/sublime_text_build_4200_x64.tar.xz"
URL="https://download.sublimetext.com/sublime_text_build_4200_x64.tar.xz"

if [ ! -e "$TARBALL" ]; then
  mkdir -p "$CACHE"
  echo "downloading $URL"
  curl -sSL -o "$TARBALL" "$URL"
fi

if [ -x "$ROOT/sublime_text" ]; then
  echo "binary already at $ROOT"
else
  mkdir -p "$ROOT"
  tar -xJf "$TARBALL" -C "$ROOT" --strip-components=1
fi

DATA="$ROOT/Data"
mkdir -p "$DATA/Packages/User" "$DATA/Installed Packages" "$DATA/Lib/python38"

link() { # link <target> <path>: replace a link, refuse to replace a real dir
  if [ -L "$2" ]; then rm "$2"; fi
  if [ -e "$2" ]; then echo "refusing to replace $2 (not a symlink)"; exit 1; fi
  ln -s "$1" "$2"
}
link "$REPO" "$DATA/Packages/MarkdownGlance"
link "$SKILL_DIR/probe" "$DATA/Packages/MdglanceProbe"

if [ ! -e "$DATA/Lib/python38/pymdownx" ]; then
  python3 -m pip install --quiet --disable-pip-version-check \
    --target "$DATA/Lib/python38" "Markdown==3.2.2" "pymdown-extensions==8.1.1"
fi

# No hot exit (a clean window every launch), no update nag, software
# rendering (works under Xvfb and in a VM), and Vintage off.
cat >"$DATA/Packages/User/Preferences.sublime-settings" <<'EOF'
{
    "hot_exit": false,
    "update_check": false,
    "hardware_acceleration": "none",
    "ignored_packages": ["Vintage"],
    "index_files": false
}
EOF
# Scenarios set their own MarkdownGlance settings in memory.
[ -e "$DATA/Packages/User/MarkdownGlance.sublime-settings" ] ||
  echo '{}' >"$DATA/Packages/User/MarkdownGlance.sublime-settings"

echo "portable Sublime Text ready at $ROOT"
ls -la "$DATA/Packages"
