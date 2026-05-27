# tech-radar

Ранжирует техдолг по группе связанных репозиториев через коэффициент **impact/effort**. Источники — GitHub issues и inline-маркеры (`TODO`/`FIXME`/`HACK`/`XXX`). LLM ставит критичность и трудозатраты, формула отдаёт ранжированную таблицу.

## Быстрый старт (без internet/git)

```
python radar.py --demo
```

Запускается на встроенном наборе из 20 элементов (`mock_data/demo_inventory.json`), не требует ни GitHub токена, ни clone'ов. На выходе:

- `inventory.json` — полный инвентарь со scoring'ом
- `report.md` — таблица топ-N с русскими заголовками (`#`, `репо`, `тип`, `локатор`, `приоритет`, `крит.`, `часы`, `связи`, `импакт`, `обоснование`)
- `report.csv` — то же в CSV

## Полный pipeline

```
python radar.py
```

Шаги:
1. Читает `repos.txt`
2. Тянет open issues через GitHub API (нужен `GITHUB_TOKEN` для адекватного rate-limit). Кэш в `.cache/issues/<owner>/<name>/`
3. Shallow-clone каждого репо в `.work/<short>/`, grep на маркерах
4. LLM-ранжирование top-N кандидатов (по умолчанию — **mock-heuristic**, оффлайн, $0)
5. Считает impact = `(1 + links) * sev² / max(cost, 1)`
6. Пишет inventory + отчёты, проверяя invariants перед save

## Параметры

```
python radar.py --help
```

Полезные флаги:

| Флаг                  | Что делает                                                              |
|-----------------------|-------------------------------------------------------------------------|
| `--demo`              | Использует bundled demo-данные, не лезет в сеть/git                     |
| `--no-llm`            | Пропустить scoring (severity останется null)                            |
| `--no-inline`         | Пропустить sweep инлайн-маркеров                                        |
| `--no-issues`         | Пропустить GitHub issues                                                |
| `--repo OWNER/NAME`   | Один репо вместо всего `repos.txt`                                      |
| `--top-n N`           | Размер top-таблицы в отчёте (default 30)                                |
| `--fresh`             | Игнорировать кэш                                                        |
| `--max-cost-usd X`    | Cap на стоимость LLM                                                    |

## Переключение mock → real LLM

В `config.json`:

```json
"ranker": {
  "mode": "openrouter",       // было "mock"
  "model": "qwen/qwen-turbo",
  "max_cost_usd": 0.50
}
```

И задать `OPENROUTER_API_KEY` в окружении. Mock-режим возвращает ту же форму записи, что и реальный LLM, — переключение не требует правок кода.

## Конфигурация

`config.json` собирает всё крутящееся в одном месте:

- `ranker.mode` — `mock` или `openrouter`
- `scan.markers`, `scan.exclude_dirs` — что/где grep
- `github.labels` — какие лейблы issues собирать
- `label_maps.priority` / `label_maps.business_value` — GitHub labels → числа
- `formula.version` / `formula.cost_floor_h` — формула impact

## Структура

```
tech-radar/
  radar.py              # CLI entry
  fetch_issues.py       # GitHub API client + 24h cache
  sweep_inline.py       # shallow clone + grep
  rank_llm.py           # mock-heuristic + openrouter scorer
  score.py              # impact formula
  render.py             # md/csv writers (Russian headers)
  invariants.py         # consistency checks before every save
  repos.txt             # group of repos
  config.json           # all weights and switches
  mock_data/
    demo_inventory.json # bundled 20-item demo
  .cache/               # raw issue JSONs (gitignored)
  .work/                # shallow clones (gitignored)
  inventory.json        # latest scored inventory
  report.md             # latest ranked top-N
  report.csv
```

## Стоимость

- Sweep + fetch: $0 (GitHub API + git clone)
- Mock LLM: $0
- Real LLM (qwen-turbo): ~$0.005 за top-200, $0.01 за top-500, hard-cap по умолчанию $0.50
