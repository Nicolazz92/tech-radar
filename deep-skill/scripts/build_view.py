#!/usr/bin/env python3
"""build_view.py — flatten output/enriched_items.json into output/score_view.json,
the compact per-item view score_tail.py consumes.

Covers EVERY item (inline markers + issues) uniformly, so a single rubric pass
re-evaluates the whole inventory — no bespoke/hand-scored carve-outs.
"""
from __future__ import annotations
import json, pathlib, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"


def main():
    enr = json.loads((OUTPUT / "enriched_items.json").read_text(encoding="utf-8"))
    rows = []
    for it in enr["items"]:
        e = it.get("enrichment") or {}
        fn = e.get("enclosing_function") or {}
        row = {
            "id": it["id"],
            "repo": it["repo"],
            "marker": it.get("marker"),
            "kind": it.get("kind", "inline_marker"),
            "loc": it["locator"],
            "txt": it.get("title_or_excerpt") or it.get("title") or "",
            "br": e.get("blast_radius") or "isolated",
            "imp": e.get("cross_repo_importers") or [],
            "fn": fn.get("name") if fn else None,
            "exp": fn.get("exported") if fn else None,
            "sig": fn.get("signature") if fn else None,
            "age": e.get("marker_age_days"),
            "author": e.get("introduced_by"),
        }
        if it.get("kind") == "issue":
            row["title"] = it.get("title")
            row["body"] = it.get("body")
            row["url"] = it.get("url")
            row["labels"] = it.get("labels") or []
        rows.append(row)

    (OUTPUT / "score_view.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    from collections import Counter
    print(f"[build_view] {len(rows)} rows -> output/score_view.json "
          f"by kind: {dict(Counter(r['kind'] for r in rows))}")


if __name__ == "__main__":
    main()
