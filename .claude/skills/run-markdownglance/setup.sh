#!/usr/bin/env bash
# Assemble a portable Sublime Text profile that runs this checkout.
#
#   .claude/skills/run-markdownglance/setup.sh [ROOT]
#   MDGLANCE_ST_BUILD=4200 .claude/skills/run-markdownglance/setup.sh [ROOT]
#
# The build is 4215 unless MDGLANCE_ST_BUILD says otherwise: the stable line
# whose plugin host is Python 3.14. 4200 is the last stable build with the
# Python 3.8 host, which the package still supports. ROOT defaults to
# $MDGLANCE_ST_ROOT, then to /tmp/mdglance-st for the default build and
# /tmp/mdglance-st-<build> for any other. The user's own Sublime Text
# configuration is never touched: everything lives under ROOT.
#
# The checkout is linked in as Data/Packages/MarkdownGlance, so an edit in the
# repository is live in the portable instance on its next start; the probe
# package is linked the same way. The two Package Control libraries the
# package declares are installed with pip into the library directory of that
# build's plugin host, in the versions the channel serves to it: which is
# where, and what, Package Control would install.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SKILL_DIR/../../.." && pwd)"
DEFAULT_BUILD=4215
BUILD="${MDGLANCE_ST_BUILD:-$DEFAULT_BUILD}"
if [ "$BUILD" = "$DEFAULT_BUILD" ]; then
  DEFAULT_ROOT=/tmp/mdglance-st
else
  DEFAULT_ROOT="/tmp/mdglance-st-$BUILD"
fi
ROOT="${1:-${MDGLANCE_ST_ROOT:-$DEFAULT_ROOT}}"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/markdownglance"
TARBALL="$CACHE/sublime_text_build_${BUILD}_x64.tar.xz"
URL="https://download.sublimetext.com/sublime_text_build_${BUILD}_x64.tar.xz"

# Build 4205 replaced the Python 3.8 plugin host with 3.14, and the channel
# serves each host its own release of the two libraries (ADR 0012).
if [ "$BUILD" -ge 4205 ]; then
  PYTHON=3.14
  LIBRARIES=("Markdown==3.11" "pymdown-extensions==12.1")
else
  PYTHON=3.8
  LIBRARIES=("Markdown==3.2.2" "pymdown-extensions==8.1.1")
fi
LIB="$ROOT/Data/Lib/python${PYTHON/./}"

if [ ! -e "$TARBALL" ]; then
  mkdir -p "$CACHE"
  echo "downloading $URL"
  curl -fsSL -o "$TARBALL" "$URL"
fi

if [ -x "$ROOT/sublime_text" ]; then
  # A root keeps its build: the library directory beside it is for one host.
  HELD="$(grep -m1 -o 'Build [0-9]*' "$ROOT/changelog.txt" 2>/dev/null || true)"
  if [ "$HELD" != "Build $BUILD" ]; then
    echo "refusing: $ROOT holds ${HELD:-an unknown build}, not build $BUILD; choose another ROOT"
    exit 1
  fi
  echo "build $BUILD already at $ROOT"
else
  mkdir -p "$ROOT"
  tar -xJf "$TARBALL" -C "$ROOT" --strip-components=1
fi

DATA="$ROOT/Data"
mkdir -p "$DATA/Packages/User" "$DATA/Installed Packages" "$LIB"

link() { # link <target> <path>: replace a link, refuse to replace a real dir
  if [ -L "$2" ]; then rm "$2"; fi
  if [ -e "$2" ]; then echo "refusing to replace $2 (not a symlink)"; exit 1; fi
  ln -s "$1" "$2"
}
link "$REPO" "$DATA/Packages/MarkdownGlance"
link "$SKILL_DIR/probe" "$DATA/Packages/MdglanceProbe"

if [ ! -e "$LIB/pymdownx" ]; then
  # Both are pure-Python wheels, so the Python running pip need not be the
  # host's: ask for the host's wheels by version and take nothing else.
  # Markdown 3.11 declares Python 3.11 or later, and an older pip holds that
  # against the Python it runs on rather than the one asked for.
  python3 -m pip install --quiet --disable-pip-version-check \
    --target "$LIB" --python-version "$PYTHON" --only-binary=:all: --no-deps \
    --ignore-requires-python "${LIBRARIES[@]}"
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

echo "portable Sublime Text $BUILD (Python $PYTHON) ready at $ROOT"
ls -la "$DATA/Packages"
ls "$LIB"
