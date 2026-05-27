"""sweep_inline.py — shallow-clone repos and grep for TODO/FIXME/HACK/XXX.

For each repo:
  1. Clone --depth=N into .work/<repo_short>/ on first run; otherwise
     git fetch + git reset --hard origin/<default>. (Without this, "incremental"
     sweeps regrep a frozen snapshot — fix from cycle-2 of prior work.)
  2. grep -rnE on the configured markers, excluding noise directories.
  3. Parse each match into an inventory item.

No LLM. No GitHub API. Cost: $0.
"""
from __future__ import annotations
import hashlib
import pathlib
import re
import shutil
import subprocess


def _short(repo):
    return repo.split("/")[1]


def _default_branch(work_dir):
    """Parse default branch from `git remote show origin`."""
    try:
        out = subprocess.check_output(
            ["git", "remote", "show", "origin"],
            cwd=str(work_dir), text=True, timeout=30,
        )
    except Exception:
        return "main"
    for line in out.splitlines():
        line = line.strip()
        if line.lower().startswith("head branch:"):
            return line.split(":", 1)[1].strip()
    return "main"


def shallow_clone_or_refresh(repo, work_root, depth):
    """Clone-or-refresh. Returns path to working copy, or None on failure."""
    work_root.mkdir(parents=True, exist_ok=True)
    target = work_root / _short(repo)
    if (target / ".git").exists():
        try:
            subprocess.run(
                ["git", "fetch", "--depth", str(depth), "origin"],
                cwd=str(target), check=True, timeout=180,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            branch = _default_branch(target)
            subprocess.run(
                ["git", "reset", "--hard", f"origin/{branch}"],
                cwd=str(target), check=True, timeout=60,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return target
        except Exception:
            # fetch failed (force-push? broken cache?) — start clean
            shutil.rmtree(target, ignore_errors=True)
    try:
        subprocess.run(
            ["git", "clone", "--depth", str(depth),
             f"https://github.com/{repo}.git", str(target)],
            check=True, timeout=900,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return target
    except Exception as e:
        print(f"[sweep] {repo}: clone failed: {e}")
        return None


def _grep_markers(work_dir, markers, exclude_dirs):
    """Return list of (rel_path, line_no, marker, excerpt)."""
    pattern = r"\b(" + "|".join(re.escape(m) for m in markers) + r")\b"
    cmd = ["grep", "-rnE", pattern]
    for d in exclude_dirs:
        cmd.extend(["--exclude-dir", d])
    cmd.append(".")
    try:
        proc = subprocess.run(
            cmd, cwd=str(work_dir), capture_output=True, text=True,
            timeout=180, errors="replace",
        )
    except Exception as e:
        print(f"[sweep] grep failed: {e}")
        return []
    out = []
    rx = re.compile(r"^\./(?P<path>[^:]+):(?P<line>\d+):(?P<rest>.*)$")
    marker_rx = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b", re.I)
    for raw in proc.stdout.splitlines():
        m = rx.match(raw)
        if not m:
            continue
        excerpt = m.group("rest").strip()
        mm = marker_rx.search(excerpt)
        marker = mm.group(1).upper() if mm else "TODO"
        out.append((m.group("path"), int(m.group("line")), marker, excerpt))
    return out


def sweep_repo(repo, work_root, cfg, scope_repos, max_per_repo=None):
    """Sweep one repo. Returns list of inventory items."""
    wd = shallow_clone_or_refresh(repo, work_root, cfg.get("clone_depth", 50))
    if wd is None:
        return []
    matches = _grep_markers(
        wd, cfg.get("markers", ["TODO", "FIXME", "HACK", "XXX"]),
        cfg.get("exclude_dirs", []),
    )
    excerpt_cap = cfg.get("max_excerpt_chars", 200)
    items = []
    own_short = _short(repo).lower()
    for rel_path, line_no, marker, excerpt in matches:
        locator = f"{rel_path}:{line_no}"
        item_id = hashlib.sha256(f"{repo}\0inline_marker\0{locator}".encode()).hexdigest()[:16]
        excerpt_text = excerpt[:excerpt_cap]
        text_low = excerpt_text.lower()
        links = sorted({
            r for r in scope_repos
            if r != repo and len(r.split("/")[1]) >= 3
            and r.split("/")[1].lower() in text_low
            and r.split("/")[1].lower() != own_short
        })
        items.append({
            "id": item_id,
            "repo": repo,
            "kind": "inline_marker",
            "marker": marker,
            "locator": locator,
            "title_or_excerpt": excerpt_text,
            "title": None,
            "body": None,
            "labels": [],
            "links": links,
            "links_count": len(links),
            "comments": 0,
            "reactions_total": 0,
            "created_at": None,
            "updated_at": None,
            "milestone_due": None,
            "number": None,
        })
        if max_per_repo and len(items) >= max_per_repo:
            break
    return items


def fetch_code_context(item, work_root, lines_around, max_chars):
    """Read ±N lines around `:line` from cloned source. Returns '' if anything fails."""
    if item.get("kind") != "inline_marker":
        return ""
    loc = item.get("locator") or ""
    if ":" not in loc:
        return ""
    path_only, line_str = loc.rsplit(":", 1)
    try:
        line = int(line_str)
    except (TypeError, ValueError):
        return ""
    target = work_root / _short(item["repo"]) / path_only
    if not target.exists():
        return ""
    try:
        all_lines = target.read_text(errors="replace").splitlines()
    except Exception:
        return ""
    if not all_lines:
        return ""
    start = max(0, line - 1 - lines_around)
    end = min(len(all_lines), line + lines_around)
    chunk = []
    for i in range(start, end):
        prefix = ">>>" if (i + 1) == line else "   "
        chunk.append(f"{prefix} {i+1:5d} {all_lines[i][:140]}")
    text = "\n".join(chunk)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... (truncated)"
    return text
