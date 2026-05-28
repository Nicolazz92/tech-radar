#!/usr/bin/env python3
"""sweep.py — find TODO/FIXME/HACK/XXX markers in cloned Go repos.

Same shape as serverside tech-radar/sweep_inline.py but operates on the
local work/ dir of deep-skill. Writes output/raw_items.json.
"""
from __future__ import annotations
import hashlib, json, os, pathlib, re, sys

# Windows consoles default to cp1251 here; force utf-8 so arrows/dashes in
# log lines don't raise UnicodeEncodeError mid-run.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
OUTPUT = ROOT / "output"
# Honor REPOS_FILE env (same as fetch.sh) so a scoped run stays coherent across
# every stage instead of sweeping the full default list and "skipping" the rest.
REPOS_FILE = pathlib.Path(os.environ.get("REPOS_FILE") or (ROOT / "repos.txt"))

MARKERS = ["TODO", "FIXME", "HACK", "XXX"]
EXCLUDE = ["vendor", "node_modules", "third_party", ".git", "docs",
           "testdata", "integration-tests", ".cache", ".work"]
EXCERPT_CAP = 200


def _short(repo): return repo.split("/", 1)[1]


def _load_repos():
    out = []
    for line in REPOS_FILE.read_text(encoding="utf-8").splitlines():
        s = line.split("#", 1)[0].strip()
        if s:
            out.append(s)
    return out


def grep_repo(repo):
    short = _short(repo)
    wd = WORK / short
    if not wd.exists():
        print(f"[sweep] {repo}: no clone at {wd} -- skipping")
        return []

    mrx = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")
    out = []
    for dirpath, dirnames, filenames in os.walk(wd):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE]
        for fn in filenames:
            if not fn.endswith(".go"):
                continue
            fpath = pathlib.Path(dirpath) / fn
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, raw_line in enumerate(text.splitlines(), start=1):
                mm = mrx.search(raw_line)
                if not mm:
                    continue
                rel = fpath.relative_to(wd).as_posix()
                excerpt = raw_line.strip()[:EXCERPT_CAP]
                marker = mm.group(1).upper()
                locator = f"{rel}:{lineno}"
                item_id = hashlib.sha256(
                    f"{repo}\0inline_marker\0{locator}".encode()).hexdigest()[:16]
                out.append({
                    "id": item_id,
                    "repo": repo,
                    "kind": "inline_marker",
                    "marker": marker,
                    "locator": locator,
                    "title_or_excerpt": excerpt,
                    "labels": [],
                })
    return out


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    repos = _load_repos()
    all_items = []
    for repo in repos:
        items = grep_repo(repo)
        all_items.extend(items)
        print(f"[sweep] {repo} ... {len(items)} markers")
    (OUTPUT / "raw_items.json").write_text(
        json.dumps({"repos": repos, "items": all_items}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"[sweep] DONE — {len(all_items)} items total → output/raw_items.json")


if __name__ == "__main__":
    main()
