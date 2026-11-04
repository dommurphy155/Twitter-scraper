#!/usr/bin/env bash
# Twitter Scraper — one-line installer.
# Usage:  curl -fsSL https://raw.githubusercontent.com/dommurphy155/Twitter-scraper/main/install.sh | bash
#         curl -fsSL ... | bash -s -- ~/some/path
set -euo pipefail

TARGET_DIR="${1:-$HOME/Twitter-scraper}"
REPO_URL="https://github.com/dommurphy155/Twitter-scraper.git"

say()  { printf "\033[1;36m==> %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m    %s\033[0m\n" "$*"; }
fail() { printf "\033[1;31m    %s\033[0m\n" "$*"; exit 1; }
ok()   { printf "\033[1;32m    %s\033[0m\n" "$*"; }

say "Twitter Scraper installer"
echo "    Target: $TARGET_DIR"
echo

# --- git ------------------------------------------------------------------
if ! command -v git >/dev/null 2>&1; then
    fail "git is not installed. Install it first (apt install git / brew install git)."
fi

if [ -d "$TARGET_DIR" ]; then
    if [ -d "$TARGET_DIR/.git" ]; then
        say "Existing clone found — pulling latest"
        git -C "$TARGET_DIR" pull --ff-only || warn "git pull failed (continuing)"
    else
        fail "$TARGET_DIR exists but is not a git repo. Move it aside or pick a different path."
    fi
else
    say "Cloning $REPO_URL"
    git clone --depth 1 "$REPO_URL" "$TARGET_DIR" || fail "git clone failed"
fi

cd "$TARGET_DIR"

# --- Python 3.10+ ---------------------------------------------------------
PY_BIN=""
for cand in python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
            PY_BIN="$cand"
            break
        fi
    fi
done
if [ -z "$PY_BIN" ]; then
    fail "Python 3.10+ not found. Install python3.12 (or python3.11/3.10) and retry."
fi
ok "Using $PY_BIN ($($PY_BIN --version 2>&1))"

# --- Run wizard -----------------------------------------------------------
say "Running setup wizard (this will create a venv, install deps, and ask for cookies)"
echo
exec "$PY_BIN" "$TARGET_DIR/scripts/setup_wizard.py"
