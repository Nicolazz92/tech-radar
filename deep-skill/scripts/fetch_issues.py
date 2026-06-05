#!/usr/bin/env python3
"""fetch_issues.py — pull OPEN GitHub issues (bug/security/tech-debt) for the
grafana group via the `gh` CLI, and emit them as inventory items in the same
schema the deep-skill pipeline already uses (kind="issue").

Writes:
  output/issue_items.json   {repos, items:[...]}   (enriched_items shape)

Each item carries a synthetic enrichment block so emit.py / score_tail.py keep
working unchanged: blast_radius=isolated, no cross-repo importers, age from
createdAt, introduced_by=author. The real signal for issues lives in the labels
and the title+body text, which score_tail reads.
"""
from __future__ import annotations
import datetime, hashlib, json, pathlib, subprocess, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"

# Per-repo high-signal labels. security* → likely severity-9 cluster;
# bug* → real defects; debt → tech-debt.
REPO_LABELS = {
    "grafana/grafana": ["type/security", "area/security",
                        "area/backend/security", "type/regression",
                        "type/bug", "type/debt"],
    "grafana/loki":    ["area/security", "type/bug"],
    "grafana/tempo":   ["security", "type/bug"],
    "grafana/mimir":   ["security", "security-update", "bug", "type/bug"],
    "grafana/k6":      ["security", "bug"],
    "grafana/alloy":   ["security", "security-needs-review", "bug"],
}

# security labels get a generous cap (we WANT all of them); bug/debt are capped
# so grafana/grafana's thousands of bugs don't swamp the inventory.
def cap_for(label):
    l = label.lower()
    if "security" in l or "vuln" in l:
        return 300
    if "debt" in l or "regression" in l:
        return 120
    return 150


def is_security(label):
    l = label.lower()
    return "security" in l or "vuln" in l


def gh_issue_list(repo, label, limit):
    cmd = ["gh", "issue", "list", "--repo", repo, "--label", label,
           "--state", "open", "--limit", str(limit),
           "--json", "number,title,body,labels,createdAt,url,author"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", timeout=120)
    except Exception as e:
        print(f"[issues] {repo} label={label}: ERROR {e}")
        return []
    if p.returncode != 0:
        print(f"[issues] {repo} label={label}: gh rc={p.returncode} "
              f"{(p.stderr or '').strip()[:160]}")
        return []
    try:
        return json.loads(p.stdout or "[]")
    except json.JSONDecodeError:
        return []


def age_days(created_iso):
    try:
        dt = datetime.datetime.fromisoformat(created_iso.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        return max(0, (now - dt).days)
    except Exception:
        return None


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    repos = list(REPO_LABELS)
    by_id = {}
    sec_hits = 0

    for repo, labels in REPO_LABELS.items():
        for label in labels:
            issues = gh_issue_list(repo, label, cap_for(label))
            print(f"[issues] {repo:20s} label={label:24s} -> {len(issues)}")
            for iss in issues:
                num = iss["number"]
                item_id = hashlib.sha256(
                    f"{repo}\0issue\0{num}".encode()).hexdigest()[:16]
                title = (iss.get("title") or "").strip()
                body = (iss.get("body") or "").strip()
                lab_names = [l["name"] for l in (iss.get("labels") or [])]
                author = ((iss.get("author") or {}) or {}).get("login")
                if item_id in by_id:
                    # already collected via another label — just merge label set
                    existing = by_id[item_id]["labels"]
                    for ln in lab_names:
                        if ln not in existing:
                            existing.append(ln)
                    continue
                if is_security(label):
                    sec_hits += 1
                # body can be huge; keep a generous but bounded snippet
                excerpt = title if not body else f"{title} — {body}"
                by_id[item_id] = {
                    "id": item_id,
                    "repo": repo,
                    "kind": "issue",
                    "marker": "ISSUE",
                    "locator": f"#{num}",
                    "url": iss.get("url"),
                    "title_or_excerpt": excerpt[:600],
                    "title": title[:300],
                    "body": body[:1500],
                    "labels": lab_names,
                    "enrichment": {
                        "enclosing_function": None,
                        "cross_repo_importers": [],
                        "marker_age_days": age_days(iss.get("createdAt")),
                        "introduced_by": author,
                        "blast_radius": "isolated",
                    },
                }

    items = list(by_id.values())
    payload = {"repos": repos, "items": items}
    (OUTPUT / "issue_items.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[issues] DONE — {len(items)} unique issues "
          f"({sec_hits} security-labeled hits) -> output/issue_items.json")


if __name__ == "__main__":
    main()
