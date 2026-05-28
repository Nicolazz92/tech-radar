#!/usr/bin/env bash
# deploy.sh — push tech-radar to a remote server (no rsync dependency).
#
# Uses tar + scp + ssh (works in Git Bash on Windows). Runs install.sh
# remotely. Bundles .env by default so the OPENROUTER_API_KEY makes it
# across — pass NO_ENV=1 to exclude.
#
# Usage:
#   HOST=<ssh-alias-or-user@host> ./deploy.sh
#
# Optional env:
#   HOST   — ssh alias (e.g. tr_prom) or user@host. Required.
#   DEST   — remote path (default ~/tech-radar — no sudo needed)
#   PORT   — host port on remote (default 8080)
#   NO_ENV=1     — don't ship local .env (will prompt on server instead)
#   ONLY_RSYNC=1 — just upload, don't run install.sh
#
# Examples:
#   HOST=tr_prom ./deploy.sh
#   HOST=root@1.2.3.4 PORT=9090 DEST=/opt/tech-radar ./deploy.sh

set -euo pipefail

log()  { printf '\033[36m[deploy]\033[0m %s\n' "$*"; }
err()  { printf '\033[31m[deploy]\033[0m %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

HOST="${HOST:-}"
DEST="${DEST:-\$HOME/tech-radar}"   # expanded remote-side
PORT="${PORT:-8080}"
NO_ENV="${NO_ENV:-0}"
ONLY_RSYNC="${ONLY_RSYNC:-0}"

[[ -n "$HOST" ]] || die "set HOST=<ssh-alias-or-user@host>. See --help."
command -v tar >/dev/null  || die "tar not found locally."
command -v scp >/dev/null  || die "scp not found locally."

cd "$(dirname "$0")"

# Resolve remote path on the server (handles $HOME expansion).
REMOTE_DEST="$(ssh "$HOST" "echo $DEST")"
[[ -n "$REMOTE_DEST" ]] || die "could not resolve remote DEST=$DEST"
log "target: $HOST:$REMOTE_DEST"

# Tar excludes — runtime state + secrets-or-not based on NO_ENV.
TAR_EXCLUDES=(
  --exclude=.git
  --exclude=.cache
  --exclude=.work
  --exclude=__pycache__
  --exclude=inventory.json
  --exclude=inventory.mock.json
  --exclude=inventory.openrouter.json
  --exclude=state
  --exclude=report.md
  --exclude=report.csv
)
if [[ "$NO_ENV" == "1" ]]; then
  TAR_EXCLUDES+=( --exclude=.env )
  log "skipping local .env (NO_ENV=1) — server will prompt during install"
else
  if [[ -f .env ]]; then
    log "INCLUDING local .env (contains OPENROUTER_API_KEY) — secrets travel over ssh-encrypted channel"
  else
    log "no local .env to ship — server will prompt during install"
  fi
fi

# Build tarball locally.
TARBALL="$(mktemp -t tech-radar.XXXXXX.tgz 2>/dev/null || echo /tmp/tech-radar-$$.tgz)"
trap 'rm -f "$TARBALL"' EXIT
log "packing → $TARBALL"
tar -czf "$TARBALL" "${TAR_EXCLUDES[@]}" .

# Ship + extract.
log "ensuring remote dir: $REMOTE_DEST"
ssh "$HOST" "mkdir -p '$REMOTE_DEST'"

log "scp tarball..."
scp -q "$TARBALL" "$HOST:/tmp/tech-radar-deploy.tgz"

log "extracting on remote..."
# shellcheck disable=SC2029
ssh "$HOST" "cd '$REMOTE_DEST' && tar -xzf /tmp/tech-radar-deploy.tgz && rm /tmp/tech-radar-deploy.tgz && chmod +x install.sh deploy.sh"

if [[ "$ONLY_RSYNC" == "1" ]]; then
  log "upload-only mode (ONLY_RSYNC=1) — skipping install.sh"
  exit 0
fi

log "running install.sh on remote..."
# shellcheck disable=SC2029
ssh "$HOST" "cd '$REMOTE_DEST' && PORT=$PORT ./install.sh"

log "DONE. open the UI at http://<server>:$PORT"
