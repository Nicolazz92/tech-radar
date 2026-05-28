#!/usr/bin/env python3
"""analyze.py — Go static analysis: AST + import graph + symbol table.

For each .go file in work/<repo>/:
  - tree-sitter-go parse → enclosing function per line, exported-ness, signature
  - parse go.mod for module path
  - parse import statements → cross-repo edges (when imported module belongs
    to another repo in scope)

Outputs:
  output/symbol_table.json   per-repo per-file func index
  output/import_graph.json   directed edges between in-scope repos
  output/call_refs.json      func → callers index (within and cross repo)
"""
from __future__ import annotations
import json, os, pathlib, re, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
OUTPUT = ROOT / "output"
# Honor REPOS_FILE env (same as fetch.sh/sweep.py) for coherent scoped runs.
REPOS_FILE = pathlib.Path(os.environ.get("REPOS_FILE") or (ROOT / "repos.txt"))


def _load_repos():
    out = []
    for line in REPOS_FILE.read_text(encoding="utf-8").splitlines():
        s = line.split("#", 1)[0].strip()
        if s:
            out.append(s)
    return out


def _import_tree_sitter():
    """Lazy-import tree-sitter so the script can at least lint without deps."""
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_go as tsg
        GO = Language(tsg.language())
        return Language, Parser, GO
    except ImportError as e:
        print(f"[analyze] tree-sitter not installed: {e}")
        print("[analyze] run: pip install -r requirements.txt")
        sys.exit(2)


def _read_go_mod(repo_dir):
    """Return module path declared in go.mod, or None."""
    p = repo_dir / "go.mod"
    if not p.exists():
        return None
    for line in p.read_text(errors="replace").splitlines():
        line = line.strip()
        if line.startswith("module "):
            return line.split(None, 1)[1].strip()
    return None


def _walk_go_files(repo_dir):
    skip = {"vendor", "node_modules", "third_party", ".git",
            "testdata", "integration-tests"}
    for p in repo_dir.rglob("*.go"):
        parts = set(p.relative_to(repo_dir).parts)
        if parts & skip:
            continue
        yield p


# === TODO (v0.0.1 implementation): walk all .go files, parse, build:
# - symbol_table[repo][file] = [{name, exported, line_start, line_end, signature}]
# - import_graph[repo_short] = set of other repos in scope referenced via go.mod path
# - call_refs[<funcname>] = [{repo, file, line}]  # within-file + cross-repo
# Tree-sitter query for Go functions:
#   (function_declaration name: (identifier) @name) @fn
#   (method_declaration receiver: (parameter_list) name: (field_identifier) @name) @fn
# Plus call_expression to gather references.


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    repos = _load_repos()

    # Stage 1 — go.mod + import_graph (cheap, do first)
    module_path_by_repo = {}
    for repo in repos:
        short = repo.split("/", 1)[1]
        d = WORK / short
        if d.exists():
            mp = _read_go_mod(d)
            if mp:
                module_path_by_repo[repo] = mp
            print(f"[analyze] {repo}: module = {mp}")

    # naive import_graph: scan all .go files for `import "<other_module>"` substring.
    import_graph = {repo: set() for repo in repos}
    other_modules = {mp: repo for repo, mp in module_path_by_repo.items()}
    for repo in repos:
        short = repo.split("/", 1)[1]
        d = WORK / short
        if not d.exists():
            continue
        for go in _walk_go_files(d):
            try:
                text = go.read_text(errors="replace")
            except Exception:
                continue
            # quick filter: look at import blocks only (faster than full parse)
            for mp, other_repo in other_modules.items():
                if other_repo == repo:
                    continue
                if mp in text and ('"' + mp) in text:
                    import_graph[repo].add(other_repo)
    # serialize sets to lists
    import_graph_ser = {r: sorted(list(s)) for r, s in import_graph.items()}
    (OUTPUT / "import_graph.json").write_text(
        json.dumps(import_graph_ser, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"[analyze] import_graph → output/import_graph.json")

    # Stage 2 — symbol_table (tree-sitter)
    Language, Parser, GO = _import_tree_sitter()
    from tree_sitter import Query, QueryCursor
    parser = Parser(GO)

    fn_query = Query(
        GO,
        """
        (function_declaration name: (identifier) @name) @fn
        (method_declaration name: (field_identifier) @name) @fn
        """,
    )
    fn_cursor = QueryCursor(fn_query)

    symbol_table = {repo: {} for repo in repos}
    for repo in repos:
        short = repo.split("/", 1)[1]
        d = WORK / short
        if not d.exists():
            continue
        n_funcs = 0
        for go in _walk_go_files(d):
            try:
                src = go.read_bytes()
                tree = parser.parse(src)
            except Exception:
                continue
            funcs = []
            # matches() keeps each function's @fn and @name in the same group;
            # captures() returns them as two separately-ordered lists that don't
            # zip reliably (corrupts the name<->signature pairing).
            for _pattern_idx, caps in fn_cursor.matches(tree.root_node):
                fn_nodes = caps.get("fn", [])
                name_nodes = caps.get("name", [])
                if not fn_nodes or not name_nodes:
                    continue
                fn_node = fn_nodes[0]
                name_node = name_nodes[0]
                name = src[name_node.start_byte:name_node.end_byte].decode("utf-8", "replace")
                line_start = fn_node.start_point[0] + 1
                line_end = fn_node.end_point[0] + 1
                # signature = first line (strip trailing CR from CRLF files)
                sig = src[fn_node.start_byte:fn_node.start_byte + 200] \
                    .decode("utf-8", "replace").split("\n", 1)[0].rstrip("\r")
                exported = name and name[:1].isupper()
                funcs.append({
                    "name": name,
                    "exported": exported,
                    "line_start": line_start,
                    "line_end": line_end,
                    "signature": sig,
                })
            if funcs:
                rel = go.relative_to(d).as_posix()
                symbol_table[repo][rel] = funcs
                n_funcs += len(funcs)
        print(f"[analyze] {repo}: {n_funcs} functions")

    (OUTPUT / "symbol_table.json").write_text(
        json.dumps(symbol_table, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"[analyze] symbol_table → output/symbol_table.json")

    # Stage 3 — call_refs: TODO для v0.0.1. Сейчас оставляем пустой.
    # Идея: для каждой exported func из symbol_table грепнуть `<funcname>(`
    # во всех ОСТАЛЬНЫХ репо. Записать как {fn_qualified → [callers]}.
    call_refs_stub = {
        "_note": "stub — v0.0.1 не вычисляет call_refs; будет в v0.0.2 через grep по exported funcs"
    }
    (OUTPUT / "call_refs.json").write_text(
        json.dumps(call_refs_stub, ensure_ascii=False, indent=2),
        encoding="utf-8")

    print("[analyze] DONE")


if __name__ == "__main__":
    main()
