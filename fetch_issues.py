"""fetch_issues.py — pull open GitHub issues for a group of repos.

Cache layout:
    .cache/issues/<owner>/<name>/issues.json  -- full paged response
    .cache/issues/<owner>/<name>/_ts           -- ISO timestamp of last fetch

Uses GITHUB_TOKEN env var if present (raises rate limit 60 → 5000 req/h).
Filters out pull requests (issues endpoint returns both, distinguished by
`pull_request` field).
"""
from __future__ import annotations
import datetime
import json
import os
import pathlib
import urllib.request
import urllib.error
import urllib.parse


_API_BASE = "https://api.github.com"


def _cache_dir(repo, root):
    owner, name = repo.split("/", 1)
    d = root / "issues" / owner / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_fresh(d, ttl_hours):
    ts_file = d / "_ts"
    if not ts_file.exists():
        return False
    try:
        last = datetime.datetime.fromisoformat(ts_file.read_text().strip())
    except Exception:
        return False
    age_h = (datetime.datetime.now(datetime.timezone.utc) - last).total_seconds() / 3600.0
    return age_h < ttl_hours


def _gh_request(url, token):
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
        link = resp.headers.get("Link", "")
    return json.loads(body), link


def _next_url(link_header):
    if not link_header:
        return None
    for chunk in link_header.split(","):
        parts = chunk.split(";")
        if len(parts) < 2:
            continue
        url_part = parts[0].strip().lstrip("<").rstrip(">")
        rel_part = parts[1].strip()
        if 'rel="next"' in rel_part:
            return url_part
    return None


def _fetch_one_label(repo, label, per_page, token):
    """Paginate issues for ONE label (or no label = all open issues)."""
    owner, name = repo.split("/", 1)
    params = {"state": "open", "per_page": str(per_page)}
    if label:
        params["labels"] = label
    url = f"{_API_BASE}/repos/{owner}/{name}/issues?{urllib.parse.urlencode(params)}"
    out = []
    while url:
        page, link = _gh_request(url, token)
        if not isinstance(page, list):
            break
        for it in page:
            if it.get("pull_request"):  # skip PRs
                continue
            out.append(it)
        url = _next_url(link)
    return out


def _fetch_paged(repo, labels, per_page, token):
    """Fetch open issues matching ANY of the labels (OR-semantics).

    Critical: GitHub API's `labels=A,B,C` does an AND (issue must have ALL
    labels) — not OR. To get "any of these labels", we paginate per-label
    and merge by issue id.
    """
    if not labels:
        return _fetch_one_label(repo, None, per_page, token)
    seen = {}
    for label in labels:
        try:
            issues = _fetch_one_label(repo, label, per_page, token)
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            # 404 on unknown label is fine — repo simply doesn't use it. Other
            # errors (rate limit, 5xx) we skip and continue with remaining labels.
            print(f"[fetch] {repo} label='{label}': {type(e).__name__} — skipping this label")
            continue
        for it in issues:
            iid = it.get("id")
            if iid is not None:
                seen[iid] = it
    return list(seen.values())


def fetch_for_repo(repo, cfg, cache_root, fresh=False):
    """Returns list of issue dicts. Uses cache unless fresh=True."""
    d = _cache_dir(repo, cache_root)
    cache_file = d / "issues.json"
    ttl = cfg.get("issues_cache_ttl_hours", 24)
    if not fresh and _cache_fresh(d, ttl) and cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    token = os.environ.get("GITHUB_TOKEN") or ""
    try:
        issues = _fetch_paged(
            repo, cfg.get("labels") or [], cfg.get("per_page", 100), token)
    except urllib.error.HTTPError as e:
        print(f"[fetch] {repo}: HTTP {e.code} — skipping")
        return []
    except urllib.error.URLError as e:
        print(f"[fetch] {repo}: network error: {e.reason} — skipping")
        return []
    cache_file.write_text(json.dumps(issues, ensure_ascii=False), encoding="utf-8")
    (d / "_ts").write_text(datetime.datetime.now(datetime.timezone.utc).isoformat())
    return issues


def issue_to_item(repo, issue, scope_repos):
    """Convert GitHub issue dict → uniform inventory item."""
    import hashlib
    labels = [l["name"] for l in (issue.get("labels") or []) if isinstance(l, dict)]
    title = issue.get("title") or ""
    body = (issue.get("body") or "")[:2000]
    locator = issue.get("html_url") or f"{repo}#{issue.get('number')}"
    item_id = hashlib.sha256(f"{repo}\0issue\0{locator}".encode()).hexdigest()[:16]
    # links: other repos in scope mentioned in title/body
    text_low = (title + " " + body).lower()
    own_short = repo.split("/")[1].lower()
    links = sorted({
        r for r in scope_repos
        if r != repo and len(r.split("/")[1]) >= 3
        and r.split("/")[1].lower() in text_low
        and r.split("/")[1].lower() != own_short
    })
    return {
        "id": item_id,
        "repo": repo,
        "kind": "issue",
        "marker": None,
        "locator": locator,
        "title_or_excerpt": title,
        "title": title,
        "body": body[:500],
        "labels": labels,
        "links": links,
        "links_count": len(links),
        "comments": issue.get("comments", 0),
        "reactions_total": (issue.get("reactions") or {}).get("total_count", 0),
        "created_at": issue.get("created_at"),
        "updated_at": issue.get("updated_at"),
        "milestone_due": ((issue.get("milestone") or {}) or {}).get("due_on"),
        "number": issue.get("number"),
    }
