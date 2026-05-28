#!/usr/bin/env bash
# fetch.sh — clone --depth=200 каждого репо из ../repos.txt в ../work/<short>.
# На повторных запусках делает git fetch + git reset --hard origin/<default>.
# depth=200 нужен для git blame на маркерах не старше ~2 лет.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPOS_FILE="${REPOS_FILE:-$ROOT/repos.txt}"
WORK="${WORK:-$ROOT/work}"
DEPTH="${DEPTH:-200}"

[[ -f "$REPOS_FILE" ]] || { echo "no repos file at $REPOS_FILE" >&2; exit 1; }
mkdir -p "$WORK"

log() { printf '\033[36m[fetch]\033[0m %s\n' "$*"; }

while IFS= read -r line; do
  # skip blanks + comments
  repo="$(echo "$line" | sed 's/#.*//' | xargs)"
  [[ -z "$repo" ]] && continue
  short="${repo##*/}"
  target="$WORK/$short"

  if [[ -d "$target/.git" ]]; then
    log "$repo → fetch+reset"
    pushd "$target" >/dev/null
    git fetch --depth="$DEPTH" origin >/dev/null 2>&1
    head_branch="$(git remote show origin 2>/dev/null \
                   | grep -i 'head branch' \
                   | awk '{print $NF}')"
    git reset --hard "origin/${head_branch:-main}" >/dev/null 2>&1
    popd >/dev/null
  else
    log "$repo → clone depth=$DEPTH"
    git clone --depth="$DEPTH" "https://github.com/$repo.git" "$target" 2>&1 \
      | grep -vE "Cloning|Updating|Receiving|Resolving|^Checking" || true
  fi
done < "$REPOS_FILE"

log "DONE — clones in $WORK"
