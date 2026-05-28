#!/usr/bin/env python3
"""radar.py — CLI entry point for tech-radar.

Pipeline:
    1. Load config + repos.txt
    2. fetch GitHub issues (cached)
    3. sweep inline TODO/FIXME (shallow clone + grep)
    4. rank top-N items via LLM (mock by default, openrouter if configured)
    5. compute impact, write inventory.json + report.md + report.csv

Usage:
    python radar.py                       # full pipeline
    python radar.py --demo                # skip sweep/fetch, use bundled demo data
    python radar.py --no-llm              # leave severity=null (signals only)
    python radar.py --no-inline           # skip git+grep
    python radar.py --no-issues           # skip GitHub API
    python radar.py --top-n 50            # show top 50 in report
    python radar.py --fresh               # ignore caches
    python radar.py --max-cost-usd 0.30   # override LLM cost cap
"""
from __future__ import annotations
import argparse
import datetime
import json
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import invariants
import rank_llm
import render
import score


# ---------------------------------------------------------------- UI server

def _serve_ui(port):
    """Tiny HTTP server: serves ui/index.html + inventory.json + API endpoints."""
    import http.server
    import socketserver
    import os  # noqa: F401 -- used in handler closure

    ui_dir = ROOT / "ui"

    if not (ui_dir / "index.html").exists():
        print(f"[serve] UI files missing at {ui_dir}")
        return 2
    # Inventory files are per-mode: inventory.mock.json / inventory.openrouter.json.
    # Toggling mock↔openrouter in the UI just switches which file is served —
    # no re-run of the LLM pipeline. Both files are allowed to be missing on
    # first start; UI shows an empty state until "Обновить" is clicked.

    def _inv_path_for_mode(mode):
        return ROOT / f"inventory.{mode}.json"

    cfg_path = ROOT / "config.json"

    # Single-flight lock for /api/refresh — without this, concurrent refresh
    # calls race on writing inventory.json (the latter writer wins, the
    # earlier writer's pipeline work is lost).
    import threading
    _refresh_lock = threading.Lock()

    def _state_payload():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
        rcfg = cfg.get("ranker") or {}
        mode = rcfg.get("mode", "mock")
        inv = {}
        ip = _inv_path_for_mode(mode)
        if ip.exists():
            try:
                inv = json.loads(ip.read_text(encoding="utf-8"))
            except Exception:
                pass
        stats = (inv.get("stats") or {})
        return {
            "mode": rcfg.get("mode", "mock"),
            "model": rcfg.get("model"),
            "openrouter_key_present": bool(os.environ.get("OPENROUTER_API_KEY")),
            "ts": inv.get("ts"),
            "items_total": stats.get("items_total", 0),
            "ranked_count": stats.get("ranked_count", 0),
            "cost_usd": ((stats.get("ranking_run") or {}).get("cost_usd")),
        }

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            print(f"[serve] {self.address_string()} {fmt % args}")

        def _send(self, status, body, ctype):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status, obj):
            return self._send(status, json.dumps(obj, ensure_ascii=False), "application/json")

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                return self._send(200, (ui_dir / "index.html").read_bytes(), "text/html")
            if path == "/style.css":
                return self._send(200, (ui_dir / "style.css").read_bytes(), "text/css")
            if path == "/app.js":
                return self._send(200, (ui_dir / "app.js").read_bytes(), "application/javascript")
            if path == "/inventory.json":
                # Serve the inventory for the CURRENT mock/openrouter mode.
                try:
                    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                except Exception:
                    cfg = {}
                mode = (cfg.get("ranker") or {}).get("mode", "mock")
                ip = _inv_path_for_mode(mode)
                if not ip.exists():
                    return self._send_json(404, {
                        "error": f"no inventory yet for mode={mode}",
                        "hint": "click «Обновить» to run the pipeline for this mode",
                    })
                return self._send(200, ip.read_bytes(), "application/json")
            if path == "/api/state":
                return self._send_json(200, _state_payload())
            return self._send_json(404, {"error": "not found", "path": path})

        def do_POST(self):
            import os, subprocess
            path = self.path.split("?", 1)[0]
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            except Exception:
                body = {}

            if path == "/api/config":
                mode = body.get("mode")
                if mode not in ("mock", "openrouter"):
                    return self._send_json(400, {"error": "mode must be 'mock' or 'openrouter'"})
                if mode == "openrouter" and not os.environ.get("OPENROUTER_API_KEY"):
                    return self._send_json(400, {
                        "error": "OPENROUTER_API_KEY not set in environment",
                        "hint": "export OPENROUTER_API_KEY=... and restart the server (or set in docker-compose .env)",
                    })
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                cfg.setdefault("ranker", {})["mode"] = mode
                cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
                return self._send_json(200, {"mode": mode})

            if path == "/api/refresh":
                # By default refresh re-runs on the bundled demo inventory (fast, no
                # network). Pass {"full": true} to run the full pipeline (clone + grep
                # + GitHub fetch + LLM) — slow. Pass {"fresh": true} to ignore caches.
                full = bool(body.get("full"))
                fresh = bool(body.get("fresh"))
                cmd = [sys.executable, str(ROOT / "radar.py")]
                if not full:
                    cmd.append("--demo")
                if fresh:
                    cmd.append("--fresh")

                # Single-flight guard: refuse a parallel refresh, return 409.
                # Without this, two concurrent refreshes race on inventory.json.
                if not _refresh_lock.acquire(blocking=False):
                    return self._send_json(409, {
                        "error": "refresh already running",
                        "hint": "wait for current refresh to finish",
                    })
                try:
                    print(f"[refresh] running: {' '.join(cmd)}", flush=True)
                    try:
                        proc = subprocess.run(cmd, cwd=str(ROOT), timeout=900)
                    except subprocess.TimeoutExpired:
                        return self._send_json(500, {"error": "pipeline timeout (>15min)"})
                    if proc.returncode != 0:
                        return self._send_json(500, {
                            "error": "pipeline failed",
                            "code": proc.returncode,
                            "hint": "check `docker logs tech-radar` for subprocess stderr",
                        })
                    return self._send_json(200, _state_payload())
                finally:
                    _refresh_lock.release()

            return self._send_json(404, {"error": "not found", "path": path})

    # ThreadingTCPServer so that a long-running /api/refresh (which subprocesses
    # the pipeline for minutes) doesn't block /api/state, health-checks, and
    # other concurrent UI requests. The Handler closures (cfg_path, inv_path,
    # _state_payload) are read-only / file-backed — no shared mutable state.
    class _Threaded(socketserver.ThreadingMixIn, socketserver.TCPServer):
        daemon_threads = True
        allow_reuse_address = True

    with _Threaded(("0.0.0.0", port), H) as httpd:
        print(f"[serve] http://localhost:{port}   (Ctrl-C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[serve] stopped")
    return 0


def _load_config():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    return cfg


def _load_repos():
    out = []
    for line in (ROOT / "repos.txt").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def _now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def _stage_fetch_issues(repos, cfg, cache_root, fresh):
    from fetch_issues import fetch_for_repo, issue_to_item
    items = []
    for repo in repos:
        print(f"[fetch] {repo} ...", end=" ", flush=True)
        raw = fetch_for_repo(repo, cfg["github"], cache_root, fresh=fresh)
        n = 0
        for issue in raw:
            items.append(issue_to_item(repo, issue, repos))
            n += 1
        print(f"{n} issues")
    return items


def _stage_sweep_inline(repos, cfg, work_root):
    from sweep_inline import sweep_repo
    items = []
    for repo in repos:
        print(f"[sweep] {repo} ...", end=" ", flush=True)
        rep_items = sweep_repo(repo, work_root, cfg["scan"], repos)
        items.extend(rep_items)
        print(f"{len(rep_items)} markers")
    return items


def _stage_rank(items, cfg, top_n, work_root, max_cost_usd):
    """Pick top-N candidates by baseline score; LLM-rank in batches; apply impact."""
    from sweep_inline import fetch_code_context

    rcfg = cfg["ranker"]
    scan = cfg["scan"]
    formula = cfg["formula"]

    def baseline(it):
        marker_weight = {"HACK": 3, "FIXME": 2, "TODO": 1, "XXX": 1}.get(it.get("marker") or "", 0)
        prio = score.priority_from_labels(it.get("labels") or [], cfg["label_maps"]["priority"])
        return (marker_weight + prio + it.get("links_count", 0),
                len((it.get("title_or_excerpt") or "")))

    candidates = sorted(items, key=baseline, reverse=True)[:top_n]
    # Attach code_context for inline markers (helps real LLM; mock ignores it)
    code_lines = scan.get("code_context_lines", 25)
    code_max = scan.get("code_context_max_chars", 2000)
    for it in candidates:
        if it.get("kind") == "inline_marker":
            it["code_context"] = fetch_code_context(
                it, work_root, code_lines, code_max,
            )

    batch_size = rcfg.get("batch_size", 20)
    spent_in = spent_out = 0.0
    price_in = float(rcfg.get("price_in_per_m", 0.033)) / 1_000_000
    price_out = float(rcfg.get("price_out_per_m", 0.130)) / 1_000_000
    cap = float(max_cost_usd if max_cost_usd is not None else rcfg.get("max_cost_usd", 0.50))
    scored = {}
    n_calls = 0
    for i in range(0, len(candidates), batch_size):
        if (spent_in + spent_out) > cap:
            print(f"[rank] cost cap reached (${spent_in + spent_out:.4f}); stopping")
            break
        chunk = candidates[i:i + batch_size]
        try:
            recs, usage = rank_llm.score_batch(chunk, rcfg)
        except Exception as e:
            print(f"[rank] batch {i} failed: {type(e).__name__}: {e}")
            continue
        for rec in recs:
            if rec and rec.get("id"):
                scored[rec["id"]] = rec
        n_calls += 1
        spent_in += (usage.get("prompt_tokens") or 0) * price_in
        spent_out += (usage.get("completion_tokens") or 0) * price_out
        cost_far = spent_in + spent_out
        print(f"[rank] batch {n_calls}: scored {len(chunk)} items, running cost ${cost_far:.4f}")

    # Apply scores
    cost_floor = float(formula.get("cost_floor_h", 1))
    ranked_count = 0
    for it in items:
        rec = scored.get(it["id"])
        if not rec:
            continue
        sev = rec.get("severity")
        if sev not in (1, 3, 9):
            continue
        fix = rec.get("fix_cost_h")
        it["severity"] = sev
        if isinstance(fix, (int, float)) and fix > 0:
            it["fix_cost_h"] = fix
        else:
            # LLM returned null/invalid despite prompt requiring a number —
            # fall back to a coarse estimate by severity so the item still ranks.
            it["fix_cost_h"] = rank_llm.fallback_cost_h(sev)
        it["rationale"] = (rec.get("rationale") or "")[:240]
        it["description"] = (rec.get("description") or "")[:600]
        it["priority_argument"] = (rec.get("priority_argument") or "")[:600]
        it["impact"] = score.compute_impact(sev, it.get("fix_cost_h"), it.get("links_count", 0), cost_floor)
        it["ranker_meta"] = {
            "ts": _now_utc().isoformat(),
            "model": rcfg.get("model", "mock") if rcfg.get("mode") != "mock" else "mock-heuristic",
            "formula_version": formula.get("version", "v1.1"),
        }
        if it["impact"] is not None:
            ranked_count += 1
    return ranked_count, n_calls, round(spent_in + spent_out, 4)


def _populate_label_signals(items, cfg):
    """Compute priority_label/business_value/engagement/deadline_days from raw signals."""
    now = _now_utc()
    for it in items:
        it["priority_label"] = score.priority_from_labels(
            it.get("labels") or [], cfg["label_maps"]["priority"])
        it["business_value"] = score.business_value_from_labels(
            it.get("labels") or [], cfg["label_maps"]["business_value"])
        it["deadline_days"] = score.deadline_days(it.get("milestone_due"), now)
        days_old = 1
        if it.get("created_at"):
            try:
                created = datetime.datetime.fromisoformat(it["created_at"].replace("Z", "+00:00"))
                days_old = max(1, (now - created).days)
            except Exception:
                pass
        it["engagement"] = score.engagement_score(
            it.get("comments", 0), it.get("reactions_total", 0), days_old)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true",
                    help="Use bundled demo inventory (no clone/fetch). Fast smoke test.")
    ap.add_argument("--no-llm", action="store_true",
                    help="Skip ranking (severity stays null).")
    ap.add_argument("--no-inline", action="store_true",
                    help="Skip inline TODO/FIXME sweep.")
    ap.add_argument("--no-issues", action="store_true",
                    help="Skip GitHub issues fetch.")
    ap.add_argument("--top-n", type=int, default=None,
                    help="Top-N for ranking + report (overrides config).")
    ap.add_argument("--fresh", action="store_true",
                    help="Ignore caches.")
    ap.add_argument("--max-cost-usd", type=float, default=None,
                    help="LLM cost cap (overrides config).")
    ap.add_argument("--repo", default=None,
                    help="Single repo (owner/name) instead of repos.txt.")
    ap.add_argument("--serve", action="store_true",
                    help="Start a tiny HTTP server with the web UI (uses existing inventory.json).")
    ap.add_argument("--port", type=int, default=8080,
                    help="Port for --serve (default 8080).")
    args = ap.parse_args()

    if args.serve:
        return _serve_ui(args.port)

    cfg = _load_config()
    cache_root = ROOT / ".cache"
    work_root = ROOT / ".work"

    if args.demo:
        demo_path = ROOT / "mock_data" / "demo_inventory.json"
        print(f"[demo] loading {demo_path}")
        items = json.loads(demo_path.read_text(encoding="utf-8"))
        repos = sorted({it["repo"] for it in items})
    else:
        repos = [args.repo] if args.repo else _load_repos()
        items = []
        if not args.no_issues:
            items.extend(_stage_fetch_issues(repos, cfg, cache_root, args.fresh))
        if not args.no_inline:
            items.extend(_stage_sweep_inline(repos, cfg, work_root))

    # Dedup by id (issue + inline_marker have distinct namespaces so no collisions expected)
    seen = {}
    for it in items:
        if it["id"] not in seen:
            seen[it["id"]] = it
    items = list(seen.values())

    print(f"[radar] {len(items)} items collected across {len(repos)} repos")

    _populate_label_signals(items, cfg)

    # Two independent knobs:
    #   report top_n  — how many rows the .md/.csv shows (from render.top_n)
    #   ranker top_n  — how many items go to the LLM (from ranker.top_n; was
    #                   render.top_n*3 — confusingly coupled)
    report_top_n = args.top_n if args.top_n is not None else cfg["render"].get("top_n", 30)
    rank_top = (args.top_n if args.top_n is not None
                else cfg["ranker"].get("top_n", 200))

    if args.no_llm:
        print("[rank] skipped (--no-llm)")
        ranked_count, n_calls, cost = 0, 0, 0.0
    else:
        ranked_count, n_calls, cost = _stage_rank(
            items, cfg, rank_top, work_root, args.max_cost_usd)
        print(f"[rank] done: {ranked_count} items, {n_calls} LLM calls, ${cost:.4f}")

    by_repo = dict(Counter(it["repo"] for it in items))
    by_kind = dict(Counter(it["kind"] for it in items))

    inv = {
        "ts": _now_utc().isoformat(),
        "scope": {"repos": repos},
        "stats": {
            "items_total": len(items),
            "items_by_repo": by_repo,
            "items_by_kind": by_kind,
            "ranked_count": sum(1 for it in items if it.get("impact") is not None),
            "formula_version": cfg["formula"]["version"] if any(it.get("impact") is not None for it in items) else None,
            "ranking_run": {
                "model": cfg["ranker"].get("model") if cfg["ranker"].get("mode") != "mock" else "mock-heuristic",
                "mode": cfg["ranker"].get("mode"),
                "items_scored": ranked_count,
                "llm_calls": n_calls,
                "cost_usd": cost,
                "ts": _now_utc().isoformat(),
            },
        },
        "items": items,
    }

    violations = invariants.check(inv)
    if violations:
        print(f"[invariants] {len(violations)} violation(s) — refusing to save:")
        for v in violations:
            print("  -", v)
        return 2

    # Per-mode atomic write: each mock/openrouter run lives in its own
    # inventory file so the UI toggle can swap between them without re-running.
    mode = cfg["ranker"].get("mode", "mock")
    inv_path = ROOT / f"inventory.{mode}.json"
    tmp_path = inv_path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(inv, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(inv_path)
    md, csv_text = render.write_outputs(inv, ROOT, top_n=report_top_n)

    print()
    print(f"[radar] wrote {inv_path.name}, report.md ({len(md)} chars), report.csv")
    print(f"[radar] top-{report_top_n} preview:")
    for line in md.split("\n")[:report_top_n + 12]:
        print(" ", line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
