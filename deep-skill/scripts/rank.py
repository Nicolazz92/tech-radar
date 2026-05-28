#!/usr/bin/env python3
"""rank.py — pick top-N candidates from enriched_items, prepare prompt chunks.

Unlike the serverside rank.py, THIS doesn't call any API. The Claude Code
session (where the skill is invoked) reads each chunk, returns a JSON answer,
and writes it to output/rankings.json. Then emit.py merges.

Two modes:
  --prepare        write output/rank_chunks/*.json — one chunk per N items
                   each chunk has prompt text + items array; Claude reads
                   and responds per-chunk
  --write-scores   given a single batch JSON (from Claude), append to
                   output/rankings.json

Workflow inside a Claude Code session:

    python scripts/rank.py --prepare --top-n 200
    # Claude (the agent) iterates over output/rank_chunks/, reads each,
    # responds with JSON, calls:
    python scripts/rank.py --write-scores < response.json

Or simpler: rank.py prints chunk-by-chunk to stdout and the agent appends.
"""
from __future__ import annotations
import argparse, json, pathlib, sys

# Rankings carry Cyrillic; force utf-8 on stdin/stdout so --write-scores doesn't
# mangle piped JSON on a cp1251 Windows console (no need to set PYTHONUTF8).
for _stream in ("stdin", "stdout"):
    try:
        getattr(sys, _stream).reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
CHUNKS_DIR = OUTPUT / "rank_chunks"


def baseline_score(it):
    marker_w = {"HACK": 3, "FIXME": 2, "TODO": 1, "XXX": 1}.get(
        it.get("marker") or "", 1)
    enr = it.get("enrichment") or {}
    br = enr.get("blast_radius") or "isolated"
    radius_w = {"fan_out": 3, "one_caller": 1, "isolated": 0}.get(br, 0)
    importers = len(enr.get("cross_repo_importers") or [])
    return marker_w + radius_w + min(importers, 5)


def prepare(top_n, batch_size):
    raw = json.loads((OUTPUT / "enriched_items.json").read_text(encoding="utf-8"))
    items = raw["items"]
    items.sort(key=baseline_score, reverse=True)
    candidates = items[:top_n]

    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    # wipe old chunks
    for p in CHUNKS_DIR.glob("*.json"):
        p.unlink()

    for i in range(0, len(candidates), batch_size):
        chunk = candidates[i:i + batch_size]
        payload = {
            "batch": i // batch_size + 1,
            "instruction": (
                "Для каждого item верни ОДИН JSON-объект со схемой:\n"
                "{\"id\":\"<id>\",\"severity\":1|3|9,\"fix_cost_h\":<число>,"
                "\"rationale\":\"<до 120 chars, ru>\","
                "\"description\":\"<1-2 предл., ru>\","
                "\"priority_argument\":\"<1-2 предл., ru>\","
                "\"cross_repo_impact\":[\"grafana/mimir\",...]}\n"
                "Severity-якоря: 9 критичный (workaround блокирует фичу, утечка, security); "
                "3 реальный (всплывает в PR/триаже); 1 косметика.\n"
                "Используй enrichment.enclosing_function (signature + exported), "
                "enrichment.cross_repo_importers и enrichment.blast_radius, "
                "чтобы оценить scope воздействия. "
                "Если функция exported и blast_radius=fan_out — severity обычно 9.\n"
                "Верни JSON-массив той же длины и порядка."
            ),
            "items": chunk,
        }
        out_path = CHUNKS_DIR / f"batch_{i//batch_size + 1:03d}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    print(f"[rank] prepared {len(candidates)} items in {len(list(CHUNKS_DIR.glob('*.json')))} chunks")
    print(f"[rank] chunks in {CHUNKS_DIR}")
    print("[rank] next: read each chunk, respond with JSON array, "
          "call rank.py --write-scores < response.json")


def write_scores():
    """Read JSON from stdin (one batch response) and append to rankings.json.

    Expected stdin shape: a JSON array of {id, severity, ...} objects.
    """
    import sys
    data = json.loads(sys.stdin.read())
    if not isinstance(data, list):
        sys.exit("[rank] stdin must be a JSON array")
    db = OUTPUT / "rankings.json"
    existing = {}
    if db.exists():
        existing = json.loads(db.read_text(encoding="utf-8"))
    for rec in data:
        if not isinstance(rec, dict) or "id" not in rec:
            continue
        existing[rec["id"]] = rec
    db.write_text(json.dumps(existing, ensure_ascii=False, indent=2),
                  encoding="utf-8")
    print(f"[rank] rankings.json now has {len(existing)} scored items")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--write-scores", action="store_true")
    ap.add_argument("--top-n", type=int, default=200)
    ap.add_argument("--batch", type=int, default=10)  # smaller than openrouter — more context per item
    args = ap.parse_args()

    if args.prepare:
        prepare(args.top_n, args.batch)
    elif args.write_scores:
        write_scores()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
