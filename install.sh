#!/usr/bin/env sh
# Comprehensive installer for cognis-digital/maritimeint (Linux / macOS).
# Tries the best available method: pipx -> uv -> pip (git+https) -> from source.
# maritimeint is source-available and not on PyPI; all paths install from GitHub.
set -eu

REPO="maritimeint"
URL="git+https://github.com/cognis-digital/maritimeint.git"
GITURL="https://github.com/cognis-digital/maritimeint.git"

say() { printf '\033[1;35m[%s]\033[0m %s\n' "$REPO" "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

if ! have python3 && ! have python; then
  say "Python 3.9+ is required but was not found. Install Python first."; exit 1
fi

if have pipx; then
  say "Installing with pipx (isolated, recommended)..."
  pipx install "$URL" && { say "Done. Run: maritimeint"; exit 0; }
fi
if have uv; then
  say "Installing with uv..."
  uv tool install "$URL" && { say "Done. Run: maritimeint"; exit 0; }
fi
if have pip3 || have pip; then
  PIP="$(command -v pip3 || command -v pip)"
  say "Installing with pip (user site)..."
  "$PIP" install --user "$URL" && { say "Done. Run: maritimeint"; exit 0; }
fi

say "No packaging tool worked; falling back to a source clone."
TMP="$(mktemp -d)"; git clone --depth 1 "$GITURL" "$TMP/$REPO"
say "Cloned to $TMP/$REPO — run: cd $TMP/$REPO && python3 -m pip install ."
