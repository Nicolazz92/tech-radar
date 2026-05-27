"""invariants.py — declarative consistency rules for inventory.json.

Each pipeline stage that writes inventory.json calls `check(inv)` before save.
Empty list = OK. Non-empty = refuse to save and surface the violations.

Adding a new rule = one function + one entry in ALL.
"""
from __future__ import annotations


def inv_items_total_matches(inv):
    actual = len(inv.get("items") or [])
    declared = (inv.get("stats") or {}).get("items_total")
    if declared is None:
        return ["stats.items_total missing"]
    if actual != declared:
        return [f"stats.items_total={declared} but items has {actual}"]
    return []


def inv_ranked_count_matches(inv):
    actual = sum(1 for it in (inv.get("items") or []) if it.get("impact") is not None)
    declared = (inv.get("stats") or {}).get("ranked_count", 0)
    if actual != declared:
        return [f"stats.ranked_count={declared} but {actual} items actually have non-null impact"]
    return []


def inv_severity_in_anchors(inv):
    out = []
    for it in inv.get("items") or []:
        sev = it.get("severity")
        if sev is None:
            continue
        if sev not in (1, 3, 9):
            out.append(f"item {it.get('id')} has severity={sev}; expected 1/3/9/null")
    return out


def inv_ranked_have_rationale(inv):
    out = []
    for it in inv.get("items") or []:
        if it.get("impact") is not None and not (it.get("rationale") or "").strip():
            out.append(f"item {it.get('id')} has impact but no rationale")
    return out


def inv_formula_version_set(inv):
    has_ranked = any(it.get("impact") is not None for it in (inv.get("items") or []))
    if has_ranked and not (inv.get("stats") or {}).get("formula_version"):
        return ["ranked items present but stats.formula_version not set"]
    return []


def inv_ids_unique(inv):
    seen = set()
    out = []
    for it in inv.get("items") or []:
        i = it.get("id")
        if i in seen:
            out.append(f"duplicate item id: {i}")
        seen.add(i)
    return out


ALL = [
    inv_items_total_matches,
    inv_ranked_count_matches,
    inv_severity_in_anchors,
    inv_ranked_have_rationale,
    inv_formula_version_set,
    inv_ids_unique,
]


def check(inv):
    out = []
    for fn in ALL:
        try:
            out.extend(fn(inv))
        except Exception as e:
            out.append(f"invariant {fn.__name__} crashed: {type(e).__name__}: {e}")
    return out


if __name__ == "__main__":
    import json, sys, pathlib
    p = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "inventory.json")
    if not p.exists():
        print(f"no inventory at {p}")
        sys.exit(0)
    v = check(json.loads(p.read_text(encoding="utf-8")))
    if v:
        print(f"VIOLATIONS ({len(v)}):")
        for x in v:
            print(" ", x)
        sys.exit(2)
    print(f"all {len(ALL)} invariants pass")
