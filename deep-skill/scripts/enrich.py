#!/usr/bin/env python3
"""enrich.py — merge raw_items + analysis + git blame → enriched_items.json.

For each item in raw_items.json:
  - lookup enclosing function from symbol_table (file + line containment)
  - check if function is exported
  - lookup cross-repo callers from call_refs (v0.0.2)
  - git blame the marker line → age_days + author
  - import_graph context: which other repos import this repo's module
  - compute blast_radius: isolated|one_caller|fan_out
"""
from __future__ import annotations
import datetime, json, pathlib, subprocess, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
OUTPUT = ROOT / "output"


def _short(repo): return repo.split("/", 1)[1]


def git_blame(repo, locator):
    """Return (age_days, author) for the given path:line in the cloned repo.

    Returns (None, None) if blame fails (file outside graft horizon, deleted etc.)
    """
    if ":" not in locator:
        return None, None
    path, line = locator.rsplit(":", 1)
    try:
        line = int(line)
    except ValueError:
        return None, None
    wd = WORK / _short(repo)
    if not wd.exists():
        return None, None
    cmd = ["git", "blame", "-L", f"{line},{line}", "--porcelain", "--", path]
    try:
        p = subprocess.run(cmd, cwd=str(wd), capture_output=True, text=True,
                           timeout=20, errors="replace")
    except Exception:
        return None, None
    if p.returncode != 0:
        return None, None
    author = None
    author_time = None
    for L in p.stdout.splitlines():
        if L.startswith("author "):
            author = L[len("author "):].strip()
        elif L.startswith("author-time "):
            try:
                author_time = int(L[len("author-time "):].strip())
            except ValueError:
                pass
    age = None
    if author_time:
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        age = int((now - author_time) // 86400)
    return age, author


def find_enclosing_fn(symbol_table, repo, locator):
    """Return enclosing function dict for path:line, or None."""
    if ":" not in locator:
        return None
    path, line = locator.rsplit(":", 1)
    try:
        line = int(line)
    except ValueError:
        return None
    funcs = symbol_table.get(repo, {}).get(path) or []
    for f in funcs:
        if f["line_start"] <= line <= f["line_end"]:
            return f
    return None


def _is_test_file(locator):
    """True for Go test files (path ends with _test.go).

    Test files are compiled only for `go test` and are NEVER imported by other
    packages, so the repo-level importer signal must not grant them cross-repo
    blast radius. Without this, a `//TODO` inside some `Xxx_test.go` in the
    dependency-hub repo (loki) inherits fan_out and monopolizes the top-N,
    which is a false positive (v0.0.1 importer signal is repo-level, not
    function-level).
    """
    path = locator.rsplit(":", 1)[0] if ":" in locator else locator
    return path.endswith("_test.go")


def cross_repo_callers_from_imports(import_graph, repo):
    """Coarse approximation: list of repos that import THIS repo's module.

    Without full call_refs (v0.0.1 doesn't compute them), the best signal we
    can give the LLM is "your code is imported by these N repos in the group."
    """
    importers = []
    for r, deps in import_graph.items():
        if r == repo:
            continue
        if repo in deps:
            importers.append(r)
    return importers


def blast_radius(enclosing, importers):
    if not enclosing:
        return "isolated"
    if not enclosing.get("exported"):
        return "isolated"
    n = len(importers or [])
    if n == 0:
        return "isolated"
    if n == 1:
        return "one_caller"
    return "fan_out"


def main():
    raw = json.loads((OUTPUT / "raw_items.json").read_text(encoding="utf-8"))
    symbol_table = json.loads((OUTPUT / "symbol_table.json").read_text(encoding="utf-8"))
    import_graph = json.loads((OUTPUT / "import_graph.json").read_text(encoding="utf-8"))

    enriched = []
    for i, it in enumerate(raw["items"]):
        enclosing = find_enclosing_fn(symbol_table, it["repo"], it["locator"])
        importers = cross_repo_callers_from_imports(import_graph, it["repo"])
        age, author = git_blame(it["repo"], it["locator"])

        # A marker inside a _test.go file is not reachable from other repos:
        # zero its effective importers so it can't inherit cross-repo blast
        # radius from the repo-level import edge.
        effective_importers = [] if _is_test_file(it["locator"]) else importers

        enrichment = {
            "enclosing_function": enclosing,
            "cross_repo_importers": effective_importers,
            "marker_age_days": age,
            "introduced_by": author,
            "blast_radius": blast_radius(enclosing, effective_importers),
        }
        enriched.append({**it, "enrichment": enrichment})

        if (i + 1) % 500 == 0:
            print(f"[enrich] {i + 1} / {len(raw['items'])}")

    out = {"repos": raw["repos"], "items": enriched}
    (OUTPUT / "enriched_items.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[enrich] DONE — {len(enriched)} items → output/enriched_items.json")


if __name__ == "__main__":
    main()
