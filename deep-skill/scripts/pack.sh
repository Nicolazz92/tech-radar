#!/usr/bin/env bash
# pack.sh — собрать deep-report.zip с inventory.deep.json и сопутствующими артефактами

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/output"

[[ -f "$OUT/inventory.deep.json" ]] || { echo "no inventory.deep.json — run emit.py first" >&2; exit 1; }

cd "$OUT"
zip -q -r deep-report.zip \
  inventory.deep.json \
  symbol_table.json \
  import_graph.json \
  call_refs.json \
  report.md \
  2>/dev/null || true

echo "[pack] → $OUT/deep-report.zip ($(du -h deep-report.zip | cut -f1))"
echo "[pack] импорт в UI: открыть http://<server>:8080 → toggle (mock/openrouter) → «Импорт…» → выбрать $OUT/deep-report.zip"
