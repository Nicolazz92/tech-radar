"""rank_llm.py — LLM-style scorer for debt items.

Two modes (see config.ranker.mode):
- "mock":       deterministic heuristic, no external calls, $0. Default.
- "openrouter": real qwen-turbo batch call via OpenRouter HTTP API.

Mock keeps prototype runnable offline and gives stable output for verification.
The two modes return identical record shapes so swapping is one config flip.

Returned per item:
    {
      "id": str,
      "severity": 1|3|9,
      "fix_cost_h": int|None,
      "rationale": str,         # ≤120 chars, Russian
      "description": str,       # 1-2 sentences
      "priority_argument": str  # 1-2 sentences
    }
"""
from __future__ import annotations
import json
import os
import re
import time
import urllib.request
import urllib.error
import hashlib


# Keywords that bump severity. Order matters: critical > moderate > cosmetic.
_KEYWORDS_CRITICAL = [
    "valid", "panic", "security", "crash", "leak", "race", "deadlock",
    "auth", "inject", "vulnerab", "critical", "broken", "корруп", "data loss",
    "потер", "сломан", "блокир", "exploit", "cve",
]
_KEYWORDS_MODERATE = [
    "refactor", "optimize", "efficient", "cleanup", "consolidate",
    "duplicate", "workaround", "wasteful", "improve", "performance",
    "оптимизац", "дубл", "повтор", "ускор",
]


def _detect_severity(item):
    """Heuristic severity for mock mode. Combines marker weight + keyword scan."""
    marker = (item.get("marker") or "").upper()
    text = " ".join([
        str(item.get("title_or_excerpt") or ""),
        str(item.get("title") or ""),
        str(item.get("body") or ""),
    ]).lower()

    if marker == "HACK":
        base = 9
    elif marker == "FIXME":
        base = 3
    elif marker == "XXX":
        base = 3
    elif marker == "TODO":
        base = 1
    else:
        # Issue without marker — defaults
        base = 3

    if any(k in text for k in _KEYWORDS_CRITICAL):
        return 9
    if any(k in text for k in _KEYWORDS_MODERATE) and base < 9:
        return max(3, base)
    return base


def _detect_cost(item, severity):
    """Heuristic fix cost in hours."""
    text = (item.get("title_or_excerpt") or item.get("title") or "").lower()
    if any(k in text for k in ["one-line", "typo", "rename", "comment", "опечат"]):
        return 1
    if "schema" in text or "migration" in text or "refactor" in text:
        return 12
    if severity == 9:
        return 8
    if severity == 3:
        return 4
    return 2


def _make_rationale(item, severity):
    marker = (item.get("marker") or "").upper()
    snippet = (item.get("title_or_excerpt") or item.get("title") or "").strip()[:90]
    snippet = snippet.replace("\n", " ").replace("|", "\\|")
    if severity == 9:
        prefix = "Несущий" if marker == "HACK" else "Реальный риск"
        return f"{prefix}: {snippet}"[:240]
    if severity == 3:
        return f"Реальный: {snippet}"[:240]
    return f"Косметика: {snippet}"[:240]


def _make_description(item, severity):
    short = (item.get("title_or_excerpt") or item.get("title") or "").strip()
    short = short.replace("\n", " ")[:200]
    return f"Маркер `{item.get('marker') or 'issue'}`. {short}"[:600]


def _make_priority_argument(item, severity):
    if severity == 9:
        return ("Высокий приоритет: фикс снимает риск/баг с горячего пути и/или "
                "разблокирует другие репо группы.")[:600]
    if severity == 3:
        return ("Средний приоритет: проявляется регулярно, требует внимания, "
                "но не блокирует фичи.")[:600]
    return "В приоритете не нужно: эстетика/мелкое улучшение."[:600]


def score_mock(items):
    """Return list of score-records aligned with input order."""
    out = []
    for it in items:
        sev = _detect_severity(it)
        cost = _detect_cost(it, sev)
        out.append({
            "id": it["id"],
            "severity": sev,
            "fix_cost_h": cost,
            "rationale": _make_rationale(it, sev),
            "description": _make_description(it, sev),
            "priority_argument": _make_priority_argument(it, sev),
        })
    return out


_PROMPT_SYS_RU = (
    "Ты оцениваешь элементы технического долга для радара приоритезации. "
    "Для каждого item верни ТОЛЬКО JSON следующей формы:\n"
    '{"id":"<id>","severity":1|3|9,"fix_cost_h":<число|null>,'
    '"rationale":"<до 120 символов, по-русски>",'
    '"description":"<1-2 предложения по-русски>",'
    '"priority_argument":"<1-2 предложения по-русски>"}\n\n'
    "Якоря severity: 9 — несущий (workaround блокирует фичу, известный класс "
    "крашей, утечка ресурсов); 3 — реальный (всплывает в PR/триаже); "
    "1 — косметика.\n\n"
    "fix_cost_h — оценка в часах; null если не можешь оценить.\n"
    "severity ставь по тому, ЧТО ДЕЛАЕТ код (handler/util/test), а не по "
    "тому, как звучит комментарий.\n\n"
    "Верни JSON-массив объектов, та же длина и порядок что на входе. "
    "Никакой прозы, markdown, комментариев."
)


def _parse_json_array(text):
    m = re.search(r"\[\s*(\{.*?\}\s*,?\s*)+\]", text, re.S)
    if not m:
        return []
    raw = m.group(0)
    try:
        return json.loads(raw)
    except Exception:
        try:
            cleaned = re.sub(r",(\s*[\]\}])", r"\1", raw)
            return json.loads(cleaned)
        except Exception:
            return []


def score_openrouter(items, cfg):
    """Real LLM call. Reads OPENROUTER_API_KEY from env. cfg = config['ranker']."""
    api_key = os.environ.get("OPENROUTER_API_KEY") or ""
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY env var missing")
    payload = []
    for it in items:
        payload.append({
            "id": it["id"],
            "repo": it.get("repo"),
            "kind": it.get("kind"),
            "marker": it.get("marker"),
            "locator": it.get("locator"),
            "text": (it.get("title_or_excerpt") or it.get("title") or "")[:200],
            "labels": it.get("labels") or [],
            "code_context": it.get("code_context") or "",
        })
    body = json.dumps({
        "model": cfg.get("model", "qwen/qwen-turbo"),
        "messages": [
            {"role": "system", "content": _PROMPT_SYS_RU},
            {"role": "user", "content": "Score these debt items. JSON array only.\n\n" + json.dumps(payload, ensure_ascii=False, indent=1)},
        ],
        "max_tokens": 6000,
        "temperature": 0.1,
    }).encode()
    req = urllib.request.Request(
        cfg.get("openrouter_url"),
        data=body,
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "X-Title": "tech-radar",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    text = data["choices"][0]["message"]["content"]
    arr = _parse_json_array(text)
    by_id = {x.get("id"): x for x in arr if isinstance(x, dict) and x.get("id")}
    return [by_id.get(it["id"]) for it in items], data.get("usage") or {}


def score_batch(items, cfg):
    """Top-level entry: dispatch by mode. Returns (records, usage_dict)."""
    mode = (cfg or {}).get("mode", "mock")
    if mode == "openrouter":
        return score_openrouter(items, cfg)
    # mock
    recs = score_mock(items)
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
    return recs, usage
