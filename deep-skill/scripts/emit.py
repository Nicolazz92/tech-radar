#!/usr/bin/env python3
"""emit.py — finalize output/inventory.deep.json in tech-radar-compatible schema.

Reads:
  output/enriched_items.json
  output/rankings.json  (from rank.py + Claude session)

Writes:
  output/inventory.deep.json
  output/report.md      (top-30 preview)

Compute impact (same formula v1.1 as serverside):
  impact = (1 + len(linked_repos)) * severity² / max(fix_cost_h, 1)
"""
from __future__ import annotations
import collections, datetime, json, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"

FORMULA_VERSION = "v1.1"
COST_FLOOR = 1.0


def compute_impact(sev, cost, links_count):
    if sev is None or cost is None:
        return None
    try:
        s = float(sev); c = float(cost)
    except (TypeError, ValueError):
        return None
    if s <= 0 or c <= 0:
        return None
    return round((1 + links_count) * s * s / max(c, COST_FLOOR), 3)


def main():
    raw = json.loads((OUTPUT / "enriched_items.json").read_text(encoding="utf-8"))
    rankings = {}
    rdb = OUTPUT / "rankings.json"
    if rdb.exists():
        rankings = json.loads(rdb.read_text(encoding="utf-8"))

    repos = raw["repos"]
    items = []
    ts_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    for it in raw["items"]:
        enriched = dict(it)
        score = rankings.get(it["id"])
        if score:
            sev = score.get("severity")
            cost = score.get("fix_cost_h")
            cri = score.get("cross_repo_impact") or []
            enriched["severity"] = sev if sev in (1, 3, 9) else None
            enriched["fix_cost_h"] = cost if isinstance(cost, (int, float)) and cost > 0 else None
            enriched["rationale"] = (score.get("rationale") or "")[:240]
            enriched["description"] = (score.get("description") or "")[:600]
            enriched["priority_argument"] = (score.get("priority_argument") or "")[:600]
            enriched["linked_repos"] = cri
            enriched["links_count"] = len(cri)
            enriched["impact"] = compute_impact(
                enriched["severity"], enriched["fix_cost_h"], len(cri))
            enriched["ranker_meta"] = {
                "ts": ts_iso,
                "model": "claude-deep-skill",
                "formula_version": FORMULA_VERSION,
            }
            # also lift cross_repo_impact into enrichment so serverside UI's
            # future drilldown can show it
            (enriched.setdefault("enrichment", {})
                ).setdefault("cross_repo_impact", cri)
        else:
            enriched["severity"] = None
            enriched["fix_cost_h"] = None
            enriched["impact"] = None
            enriched["linked_repos"] = []
            enriched["links_count"] = 0
        items.append(enriched)

    ranked = sum(1 for it in items if it.get("impact") is not None)
    by_repo = dict(collections.Counter(it["repo"] for it in items))
    by_kind = dict(collections.Counter(it["kind"] for it in items))

    inv = {
        "ts": ts_iso,
        "scope": {"repos": repos},
        "stats": {
            "items_total": len(items),
            "ranked_count": ranked,
            "formula_version": FORMULA_VERSION if ranked else None,
            "items_by_repo": by_repo,
            "items_by_kind": by_kind,
            "ranking_run": {
                "ts": ts_iso,
                "model": "claude-deep-skill",
                "mode": "deep",
                "items_scored": ranked,
                "llm_calls": 0,
                "cost_usd": 0,
            },
        },
        "items": items,
    }

    (OUTPUT / "inventory.deep.json").write_text(
        json.dumps(inv, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[emit] wrote inventory.deep.json — {len(items)} items, {ranked} ranked")

    # Tiny report.md preview
    ranked_items = sorted(
        (it for it in items if it.get("impact") is not None),
        key=lambda x: -x["impact"])
    md = ["# deep-tech-radar — " + ts_iso[:10], "",
          f"{len(items)} items, {ranked} ranked, model=claude-deep-skill", "",
          "| # | repo | locator | sev | h | impact | blast | rationale |",
          "|---|------|---------|-----|---|--------|-------|-----------|"]
    for i, it in enumerate(ranked_items[:30], 1):
        enr = it.get("enrichment") or {}
        md.append(
            f"| {i} | {it['repo'].split('/')[1]} | `{it['locator']}` | "
            f"{it.get('severity','—')} | {it.get('fix_cost_h','—')} | "
            f"{it.get('impact','—')} | {enr.get('blast_radius','—')} | "
            f"{(it.get('rationale') or '—')[:80]} |")
    (OUTPUT / "report.md").write_text("\n".join(md), encoding="utf-8")
    print(f"[emit] report.md preview written")


if __name__ == "__main__":
    main()
