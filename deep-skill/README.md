# deep-skill — code-aware tech-debt analyzer (Go)

Локальный pipeline, который делает то же что серверный `tech-radar`, но:

- Скачивает группу репо сам (clone --depth=200)
- Делает Go-specific static analysis (tree-sitter-go AST + import graph)
- Подмешивает git blame, exported-ness, cross-repo callers
- Использует Claude (через активную Claude Code сессию), не OpenRouter API
- Производит `inventory.deep.json` — формат-совместимый с серверным UI
- На сервер ничего не выкладывает — отчёт импортируется в UI через кнопку «Импорт»

## Когда использовать

- Когда серверный openrouter-режим дал поверхностные обоснования и хочется увидеть
  *почему* фикс важен в контексте cross-repo связей
- Когда нужно прогнать больше чем top-200 (in-session не упирается в per-token биллинг)
- Когда хочется понимать: «эта функция exported и зовётся из 3 других репо группы» —
  это уже не «изолированный TODO», а узел архитектуры

## Pipeline

```
1. fetch.sh       git clone --depth=200 каждый репо из repos.txt в .work/
2. sweep.py       grep TODO|FIXME|HACK|XXX → raw_items.json
3. analyze.py     tree-sitter-go для каждого .go файла →
                  symbol_table.json  ({repo, file, fn, exported, signature, body_lines})
                  import_graph.json  (repo A → repo B через go.mod + import statements)
                  call_refs.json     ({fn} → [(repo, file:line)])
                  git blame для каждого маркера → age_days + author
4. enrich.py      объединить raw_items + analysis → enriched_items.json
                  каждый item имеет:
                    enclosing_function: {name, exported, file, line_start, line_end, signature}
                    cross_repo_callers: [{repo, file:line, fn}]
                    marker_age_days, introduced_by
                    blast_radius: 'isolated' | 'one_caller' | 'fan_out'
5. rank.py        для каждого top-N item:
                  Claude (через активную сессию) читает enclosing function целиком
                  + cross_repo_callers + import graph context
                  → severity, fix_cost_h, rationale, description, priority_argument
                  + новое: cross_repo_impact, blast_radius
6. emit.py        пишет inventory.deep.json в схеме совместимой с tech-radar UI
                  (плюс namespace `enrichment.*` для специфичных полей)
7. pack.sh        складывает inventory.deep.json + симвоn_table.json + import_graph.json
                  в deep-report.zip
```

## Импорт в UI

После прогона:

1. Открой http://<server>:8080
2. Toggle на `openrouter` (или какой режим хочешь перезатереть)
3. Кнопка **«Импорт…»** → выбрать `inventory.deep.json` или `deep-report.zip`
4. Сервер валидирует через `invariants.check`, кладёт в `state/inventory.<mode>.json`
5. UI сразу подтягивает данные

## Структура

```
deep-skill/
  README.md                 — этот файл
  SKILL.md                  — manifest для Claude Code (когда вызывать, как идти)
  repos.txt                 — список репо (default: тот же что в tech-radar/)
  requirements.txt          — tree-sitter, tree-sitter-go
  scripts/
    fetch.sh                — git clone depth=200
    sweep.py                — grep markers
    analyze.py              — tree-sitter-go AST + import graph
    enrich.py               — merge + git blame
    rank.py                 — Claude ranking (выводит chunks для агента)
    emit.py                 — finalize inventory.deep.json
    pack.sh                 — zip артефакты
  cache/                    — gitignored, кэш разбора AST по SHA
  work/                     — gitignored, shallow clones
  output/                   — gitignored, inventory.deep.json + zip
```

## Что НЕ делает (намеренно)

- Не запускается на сервере. Тяжёлая статика + AST — это локальная задача.
- Не обновляет автоматически. Запуск из CC-сессии руками.
- Не поддерживает другие языки. Grafana stack — Go. Python/TS/JS подсунутся позже.
- Не делает full call-graph через весь репо. Только cross-repo edges и within-file callers.

## Будущие версии

- v0.0.2 — Python через tree-sitter-python
- v0.0.3 — TS/JS
- v0.1.0 — нормальный CLI (`deep-radar build`, `deep-radar import`)
- v0.2.0 — incremental кэш по git SHA (не пересчитывать симвоn-table если SHA не менялся)
