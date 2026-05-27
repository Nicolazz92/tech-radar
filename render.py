"""render.py — writes report.md (Russian headers) + report.csv.

Reads inventory.json, picks top-N by impact, formats table.
"""
from __future__ import annotations
import csv
import datetime
import io
import json
import pathlib


_PRIORITY_TEXT = {9: "high", 6: "high", 3: "medium", 1: "low"}


def _locator_md(it):
    if it["kind"] == "issue":
        url = it.get("locator") or ""
        n = it.get("number")
        label = f"#{n}" if n else url
        return f"[{label}]({url})"
    return f"`{it.get('locator', '')}`"


def _repo_short(repo):
    if "/" in repo:
        return repo.split("/", 1)[1]
    return repo


def _priority_text(item):
    """Try priority from labels first; fall back to severity if no label."""
    from score import priority_from_labels
    # Caller already populated label-derived priority. We just label it.
    p = item.get("priority_label")
    if p is None:
        sev = item.get("severity") or 1
        p = sev
    return _PRIORITY_TEXT.get(p, str(p))


def _impact_text(v):
    if v is None:
        return "—"
    return f"{v:.1f}"


def render_markdown(inv, top_n=30):
    items = inv.get("items") or []
    ranked = [it for it in items if it.get("impact") is not None]
    ranked.sort(key=lambda x: x["impact"], reverse=True)

    stats = inv.get("stats") or {}
    by_repo = stats.get("items_by_repo") or {}
    rrun = stats.get("ranking_run") or {}
    today = datetime.date.today().isoformat()
    fv = stats.get("formula_version", "n/a")

    out = []
    out.append(f"# Tech Debt Radar — {today}")
    out.append("")
    out.append(
        f"Группа из {len(by_repo)} репозиториев. Всего задач: {stats.get('items_total', 0)}. "
        f"Ранжировано: {stats.get('ranked_count', 0)} "
        f"(ranker: {rrun.get('model', 'n/a')}; формула {fv})."
    )
    out.append("")
    out.append("## Топ по импакту")
    out.append("")
    out.append("| # | репо | тип | локатор | приоритет | крит. | часы | связи | импакт | обоснование |")
    out.append("|---|------|-----|---------|-----------|-------|------|-------|--------|-------------|")
    for i, it in enumerate(ranked[:top_n], 1):
        kind = it.get("kind") or ""
        kind_short = "inline" if kind == "inline_marker" else "issue"
        sev = it.get("severity")
        cost = it.get("fix_cost_h")
        links = ", ".join(_repo_short(r) for r in (it.get("links") or [])) or "—"
        rationale = (it.get("rationale") or "").replace("|", "\\|").replace("\n", " ")
        out.append(
            f"| {i} | {_repo_short(it['repo'])} | {kind_short} | {_locator_md(it)} | "
            f"{_priority_text(it)} | {sev if sev is not None else '—'} | "
            f"{cost if cost is not None else '—'} | {links} | {_impact_text(it.get('impact'))} | "
            f"{rationale or '—'} |"
        )
    out.append("")
    out.append("## Покрытие по репозиториям")
    out.append("")
    out.append("| репо | всего | ранжировано |")
    out.append("|------|-------|-------------|")
    ranked_by_repo = {}
    for it in items:
        if it.get("impact") is not None:
            ranked_by_repo[it["repo"]] = ranked_by_repo.get(it["repo"], 0) + 1
    for repo, n in sorted(by_repo.items(), key=lambda x: -x[1]):
        out.append(f"| {repo} | {n} | {ranked_by_repo.get(repo, 0)} |")
    out.append("")
    return "\n".join(out)


def render_csv(inv, top_n=30):
    items = inv.get("items") or []
    ranked = [it for it in items if it.get("impact") is not None]
    ranked.sort(key=lambda x: x["impact"], reverse=True)

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["#", "репо", "тип", "локатор", "приоритет", "крит.", "часы", "связи", "импакт", "обоснование"])
    for i, it in enumerate(ranked[:top_n], 1):
        kind = it.get("kind") or ""
        kind_short = "inline" if kind == "inline_marker" else "issue"
        links = ", ".join(_repo_short(r) for r in (it.get("links") or []))
        w.writerow([
            i, _repo_short(it["repo"]), kind_short, it.get("locator", ""),
            _priority_text(it), it.get("severity") or "",
            it.get("fix_cost_h") or "",
            links, it.get("impact") or "",
            (it.get("rationale") or "").replace("\n", " "),
        ])
    return buf.getvalue()


def write_outputs(inv, out_dir, top_n=30):
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md = render_markdown(inv, top_n)
    csv_text = render_csv(inv, top_n)
    (out_dir / "report.md").write_text(md, encoding="utf-8")
    (out_dir / "report.csv").write_text(csv_text, encoding="utf-8")
    return md, csv_text
