#!/usr/bin/env bash
# pack.sh — собрать deep-report.zip с inventory.deep.json и сопутствующими артефактами

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/output"

[[ -f "$OUT/inventory.deep.json" ]] || { echo "no inventory.deep.json — run emit.py first" >&2; exit 1; }

cd "$OUT"
FILES="inventory.deep.json symbol_table.json import_graph.json call_refs.json report.md"

if command -v zip >/dev/null 2>&1; then
  zip -q -r deep-report.zip $FILES
else
  # No zip binary (e.g. Windows/Git Bash) — use Python's stdlib zipfile.
  python - "$FILES" <<'PY'
import sys, zipfile, pathlib
files = sys.argv[1].split()
with zipfile.ZipFile("deep-report.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for f in files:
        if pathlib.Path(f).exists():
            z.write(f)
PY
fi

[[ -f deep-report.zip ]] || { echo "[pack] failed to create deep-report.zip" >&2; exit 1; }
echo "[pack] -> $OUT/deep-report.zip ($(du -h deep-report.zip | cut -f1))"
echo "[pack] импорт в UI: открыть http://<server>:8080 → toggle (mock/openrouter) → «Импорт…» → выбрать $OUT/deep-report.zip"
