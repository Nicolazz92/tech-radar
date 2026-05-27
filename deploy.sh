#!/usr/bin/env bash
# deploy.sh — push tech-radar to a remote server and run install.sh.
#
# Runs from your local machine (where the repo is checked out). Rsyncs the
# project to the server, then ssh's in to run install.sh.
#
# Usage:
#   HOST=<ssh-alias-or-host> ./deploy.sh
#
# Optional env:
#   HOST       — ssh alias (e.g. tr_prom) or user@host. Required.
#   DEST       — remote path (default /opt/tech-radar)
#   PORT       — host port on remote (default 8080)
#   SKIP_KEY=1 — pass --no-key to install.sh (don't touch .env)
#
# Examples:
#   HOST=tr_prom ./deploy.sh
#   HOST=root@1.2.3.4 PORT=9090 ./deploy.sh

set -euo pipefail

log()  { printf '\033[36m[deploy]\033[0m %s\n' "$*"; }
err()  { printf '\033[31m[deploy]\033[0m %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

HOST="${HOST:-}"
DEST="${DEST:-/opt/tech-radar}"
PORT="${PORT:-8080}"

[[ -n "$HOST" ]] || die "set HOST=<ssh-alias-or-user@host>. See --help."
command -v rsync >/dev/null || die "rsync not found locally (install: 'pacman -S rsync' on git-bash, 'apt install rsync' on linux)."

cd "$(dirname "$0")"

# Ensure remote dir exists.
log "ensuring $DEST exists on $HOST..."
ssh "$HOST" "mkdir -p $DEST"

# Rsync. Exclude runtime state — let install.sh / docker rebuild.
log "syncing files to $HOST:$DEST ..."
rsync -avz --delete \
  --exclude '.git/' \
  --exclude '.cache/' \
  --exclude '.work/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude 'inventory.json' \
  --exclude 'report.md' \
  --exclude 'report.csv' \
  --exclude '.env' \
  ./ "$HOST:$DEST/"

log "running install.sh on $HOST..."
INSTALL_FLAGS=""
[[ "${SKIP_KEY:-0}" == "1" ]] && INSTALL_FLAGS="--no-key"

# shellcheck disable=SC2029
ssh "$HOST" "cd $DEST && chmod +x install.sh && PORT=$PORT ./install.sh $INSTALL_FLAGS"

log "DONE. open http://$HOST:$PORT (or http://<server-ip>:$PORT if HOST is an ssh alias)"
