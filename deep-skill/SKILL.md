---
name: deep-tech-radar
description: Локальный code-aware analyzer tech-debt по группе Go-репо. Делает AST-разбор tree-sitter-go, import graph, git blame, и ранжирует через активную Claude-сессию. Результат — inventory.deep.json, импортируемый в серверный tech-radar UI.
when_to_use:
  - Пользователь говорит «deep radar», «глубокий анализ», «прогон скилла»
  - Хочется обоснований с учётом cross-repo связей (а не substring match)
  - Хочется прогнать больше чем top-200 — Claude в сессии не упирается в OpenRouter биллинг
out_of_scope:
  - Языки кроме Go (v0.0.1)
  - Запуск на сервере (это локальный pipeline)
  - Автоматический деплой результата (отчёт импортируется вручную через UI)
---

# deep-tech-radar — что делать когда меня вызывают

## Шаги

1. **Подтвердить рабочую папку**: `cd <repo>/tech-radar/deep-skill`
2. **Прочитать `repos.txt`** в текущей папке (или один уровнем выше — в `../repos.txt` от tech-radar)
3. **Установить deps** если первый запуск: `pip install -r requirements.txt`
   (tree-sitter ≥0.25, tree-sitter-go — нужен Query()/QueryCursor API)
4. **fetch**: `bash scripts/fetch.sh` — clone --depth=200 каждый репо в `./work/`.
   Если репо уже есть — `git fetch + git reset --hard origin/<default>`.

   **Первый/проверочный прогон — сначала scoped.** Не клонируй сразу весь набор
   (там `grafana/grafana` — сотни МБ + tree-sitter по тысячам .go). Положи 1-2
   мелких репо (напр. tempo, k6) в отдельный файл и прогони весь pipeline через
   `REPOS_FILE`, убедись что стадии дают выхлоп, потом расширяй:
   ```bash
   REPOS_FILE="$PWD/repos.firstrun.txt" bash scripts/fetch.sh
   REPOS_FILE="$PWD/repos.firstrun.txt" python scripts/sweep.py
   REPOS_FILE="$PWD/repos.firstrun.txt" python scripts/analyze.py
   ```
   `fetch.sh`, `sweep.py`, `analyze.py` все уважают `REPOS_FILE`; `enrich.py`
   берёт набор репо из `raw_items.json`, так что отдельного env ему не нужно.
5. **sweep**: `python scripts/sweep.py` — grep маркеров → `output/raw_items.json`
6. **analyze**: `python scripts/analyze.py` — для всех .go файлов:
   - tree-sitter-go AST → enclosing function каждой строки, exported-ness, signature
   - go.mod парсинг → import_graph между репо
   - per-symbol callers index
   → `output/symbol_table.json`, `output/import_graph.json`, `output/call_refs.json`
7. **enrich**: `python scripts/enrich.py` — соединить raw_items + analysis + git blame:
   - для каждого item добавить `enclosing_function`, `cross_repo_callers`,
     `marker_age_days`, `introduced_by`, `blast_radius`
   → `output/enriched_items.json`
8. **rank**: ранжировать top-N items. Для каждого item я (Claude) получаю:
   - marker + комментарий
   - ВСЯ enclosing function (signature + полное тело)
   - cross_repo_callers (список конкретных мест откуда зовут)
   - import graph context («этот файл импортируется в N других репо»)
   - marker age + author из git blame
   
   Отвечаю по схеме:
   ```json
   {
     "id": "...",
     "severity": 1|3|9,
     "fix_cost_h": <число>,
     "rationale": "<до 120 chars, ru>",
     "description": "<1-2 предложения, ru>",
     "priority_argument": "<1-2 предложения, ru>",
     "cross_repo_impact": ["grafana/mimir", ...],
     "blast_radius": "isolated"|"one_caller"|"fan_out"
   }
   ```
   
   Скрипт `scripts/rank.py` готовит чанки и собирает ответы.
9. **emit**: `python scripts/emit.py` — финализирует `output/inventory.deep.json`
   в формате серверного tech-radar + namespace `enrichment.*`
10. **pack**: `bash scripts/pack.sh` — `output/inventory.deep.json + symbol_table.json
    + import_graph.json` → `output/deep-report.zip`
11. **Сказать пользователю**: куда положил `deep-report.zip` и как импортировать
    в UI (toggle на нужный режим → кнопка «Импорт» → выбрать файл).

## Что НЕ делать

- Не пушить ничего на tr_prom или другой сервер — это локальный pipeline
- Не редактировать tech-radar/* код — скилл только пишет в `deep-skill/output/`
- Не очищать `work/` между запусками — там cache shallow-клонов, переиспользуется
- Не делать ranking каждый раз если содержимое не менялось — кэш по `<repo>@<sha>`

## Окружение и подводные камни (проверено на Windows)

- **Кодировка**: скрипты сами форсят utf-8 на stdout/stdin
  (`sys.std*.reconfigure`), так что `PYTHONUTF8=1` ставить НЕ нужно — кириллица
  в логах и в pipe `rank.py --write-scores` не бьётся о cp1251-консоль.
- **Без внешнего grep**: `sweep.py` обходит файлы на чистом Python (внешний
  `grep` на Windows из Python падает с `WinError 267`).
- **Без внешнего zip**: `pack.sh` использует `zip` если он есть, иначе fallback
  на python `zipfile` — архив соберётся в любом случае.
- **`blast_radius`**: будет `isolated` для ВСЕХ items, если в scope нет репо,
  которые импортируют друг друга. Это не баг — `fan_out`/`one_caller` появляются
  только когда в наборе есть взаимные import-рёбра (см. `import_graph.json`).
  Для осмысленного cross-repo сигнала держи в scope ≥2 связанных репо.

## Output schema (краткий контракт)

`inventory.deep.json`:

```json
{
  "ts": "<ISO-8601 UTC>",
  "scope": {"repos": [...]},
  "stats": {
    "items_total": <N>,
    "ranked_count": <K>,
    "formula_version": "v1.1",
    "ranking_run": {
      "model": "claude-deep-skill",
      "mode": "deep",
      "items_scored": <K>,
      "llm_calls": 0,
      "cost_usd": 0,
      "ts": "..."
    },
    "items_by_repo": {...},
    "items_by_kind": {"inline_marker": <N>}
  },
  "items": [
    {
      "id", "repo", "kind", "marker", "locator",
      "title_or_excerpt", "labels", "linked_repos",
      "severity", "fix_cost_h", "impact",
      "rationale", "description", "priority_argument",
      "ranker_meta": {"ts", "model", "formula_version"},
      "enrichment": {
        "enclosing_function": {
          "name", "exported", "file", "line_start", "line_end", "signature"
        },
        "cross_repo_callers": [{"repo", "file", "line", "fn"}],
        "marker_age_days": <int>,
        "introduced_by": "<git author>",
        "blast_radius": "isolated"|"one_caller"|"fan_out"
      }
    }
  ]
}
```

Серверный UI читает items по знакомым полям; `enrichment.*` сейчас не показывается
(будущий drilldown drawer может).
