# tech-radar — single-process container with the prototype pipeline + web UI.
#
# - python:3.12-slim base (stdlib-only deps, no pip install needed)
# - git installed so sweep_inline can shallow-clone repos when --full pipeline runs
# - Non-root user for safety
# - Inventory/.cache/.work persist via named volumes mounted by docker-compose.
FROM python:3.12-slim

# git needed for the inline-marker sweep; curl handy for healthchecks/debug.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl \
 && rm -rf /var/lib/apt/lists/*

# Run as non-root.
RUN useradd -m -u 1000 radar

# Create /app + cache/work subdirs as radar-owned BEFORE WORKDIR/COPY/USER.
# Why each piece:
# - /app: WORKDIR creates missing dirs as root; COPY --chown only sets file
#   ownership, not the destination directory. Without this radar can't write
#   new files into /app (e.g. inventory.json).
# - /app/.cache, /app/.work: these become docker named-volume mountpoints. On
#   first volume creation Docker preserves the image's ownership of the path,
#   so we pre-create them radar-owned. Otherwise the volume defaults to root
#   and radar can't write GitHub issue cache or shallow clones into them.
RUN mkdir -p /app /app/.cache /app/.work \
 && chown -R radar:radar /app
WORKDIR /app

# Copy source (see .dockerignore for what is excluded).
COPY --chown=radar:radar . /app/

USER radar

# Pre-generate demo inventory so the first /api/state has data and the UI
# isn't empty on first run. Now strict: any failure here fails the build —
# that's the point, we want it visible.
RUN python radar.py --demo --top-n 30

EXPOSE 8080

# Healthcheck hits the read-only state endpoint; doesn't need inventory present.
HEALTHCHECK --interval=30s --timeout=4s --retries=3 --start-period=5s \
  CMD curl -fsS http://localhost:8080/api/state >/dev/null || exit 1

CMD ["python", "radar.py", "--serve", "--port", "8080"]
