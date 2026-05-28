#!/usr/bin/env python3
"""sweep.py — find TODO/FIXME/HACK/XXX markers in cloned Go repos.

Same shape as serverside tech-radar/sweep_inline.py but operates on the
local work/ dir of deep-skill. Writes output/raw_items.json.
"""
from __future__ import annotations
import hashlib, json, pathlib, re, subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
OUTPUT = ROOT / "output"
REPOS_FILE = ROOT / "repos.txt"

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
        print(f"[sweep] {repo}: no clone at {wd} — skipping")
        return []
    pattern = r"\b(" + "|".join(MARKERS) + r")\b"
    cmd = ["grep", "-rnE", pattern, "--include=*.go"]
    for d in EXCLUDE:
        cmd.extend(["--exclude-dir", d])
    cmd.append(".")
    try:
        p = subprocess.run(cmd, cwd=str(wd), capture_output=True, text=True,
                           timeout=180, errors="replace")
    except Exception as e:
        print(f"[sweep] {repo}: grep failed — {e}")
        return []

    out = []
    rx = re.compile(r"^\./(?P<path>[^:]+):(?P<line>\d+):(?P<rest>.*)$")
    mrx = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b", re.I)
    for raw in p.stdout.splitlines():
        m = rx.match(raw)
        if not m:
            continue
        path = m.group("path")
        line = int(m.group("line"))
        excerpt = m.group("rest").strip()[:EXCERPT_CAP]
        mm = mrx.search(excerpt)
        marker = mm.group(1).upper() if mm else "TODO"
        locator = f"{path}:{line}"
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
