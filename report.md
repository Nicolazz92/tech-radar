# Tech Debt Radar — 2026-05-27

Группа из 6 репозиториев. Всего задач: 20. Ранжировано: 20 (ranker: mock-heuristic; формула v1.1).

## Топ по импакту

| # | репо | тип | локатор | приоритет | крит. | часы | связи | импакт | обоснование |
|---|------|-----|---------|-----------|-------|------|-------|--------|-------------|
| 1 | loki | inline | `pkg/storage/stores/index/stats/stats.go:78` | low | 9 | 8 | tempo, mimir | 30.4 | Реальный риск: FIXME: fix inflated stats — race condition causes counts to drift across mimir and tempo |
| 2 | grafana | inline | `pkg/registry/apis/provisioning/resources/parser.go:293` | low | 9 | 8 | tempo | 20.2 | Реальный риск: FIXME: validation is disabled here — risk of malformed dashboards reaching backend handler |
| 3 | grafana | inline | `pkg/services/auth/session.go:142` | low | 9 | 8 | — | 10.1 | Несущий: HACK: skip auth check for legacy clients; remove after deprecation window |
| 4 | k6 | inline | `internal/js/modules/k6/webcrypto/algorithm.go:191` | low | 9 | 8 | — | 10.1 | Несущий: HACK: hard-coded HMAC algorithm name lookup — broken cryptographic ops if algo missing |
| 5 | alloy | inline | `internal/component/common/relabel/relabel.go:174` | low | 9 | 8 | — | 10.1 | Реальный риск: TODO: add support for different validation schemes |
| 6 | grafana | inline | `pkg/storage/unified/search/bleve.go:2262` | low | 9 | 8 | — | 10.1 | Реальный риск: FIXME: critical search logic depends on field analytics — review and optimize |
| 7 | mimir | issue | [#9876](https://github.com/grafana/mimir/issues/9876) | high | 9 | 8 | — | 10.1 | Реальный риск: Resource leak in query-frontend under high concurrency |
| 8 | grafana | issue | [#55555](https://github.com/grafana/grafana/issues/55555) | high | 9 | 8 | — | 10.1 | Реальный риск: Auth bypass possible via crafted SSO callback URL |
| 9 | grafana | inline | `pkg/api/dashboard_test.go:201` | low | 9 | 8 | — | 10.1 | Реальный риск: FIXME: this test is flaky — workaround with sleep, fix the race instead |
| 10 | loki | inline | `pkg/ingester/wal.go:88` | low | 9 | 8 | — | 10.1 | Реальный риск: FIXME: WAL recovery can crash on partial write — needs proper error handling and replay |
| 11 | tempo | inline | `modules/distributor/distributor.go:512` | low | 9 | 8 | — | 10.1 | Реальный риск: FIXME: inefficient unmarshal — slow path for large traces causes ingest backlog |
| 12 | alloy | issue | [#8888](https://github.com/grafana/alloy/issues/8888) | high | 9 | 8 | — | 10.1 | Реальный риск: Memory leak in prometheus.remote_write component during reload |
| 13 | alloy | issue | [#7777](https://github.com/grafana/alloy/issues/7777) | low | 9 | 12 | — | 6.8 | Реальный риск: Refactor: consolidate config validation across components |
| 14 | mimir | inline | `pkg/streamingpromql/types/hpoint_ring_buffer.go:225` | low | 3 | 4 | — | 2.2 | Реальный: FIXME: ForEach overhead — had to expose internal struct, breaks encapsulation but no other |
| 15 | mimir | inline | `pkg/streamingpromql/types/fpoint_ring_buffer.go:350` | low | 3 | 4 | — | 2.2 | Реальный: FIXME: same as hpoint_ring_buffer — performance workaround in fpoint path |
| 16 | tempo | issue | [#4567](https://github.com/grafana/tempo/issues/4567) | low | 3 | 4 | — | 2.2 | Реальный: Cleanup deprecated config flags removed in v3 |
| 17 | k6 | inline | `lib/options.go:412` | low | 3 | 4 | — | 2.2 | Реальный: TODO: clean up — duplicate option parsing for cli vs config file |
| 18 | loki | issue | [#12345](https://github.com/grafana/loki/issues/12345) | high | 3 | 12 | mimir | 1.5 | Реальный: Refactor query path to share types with mimir streaming PromQL |
| 19 | tempo | inline | `pkg/util/test/helpers.go:18` | low | 1 | 1 | — | 1.0 | Косметика: TODO: rename helper for clarity |
| 20 | mimir | inline | `pkg/distributor/distributor.go:1024` | low | 1 | 2 | — | 0.5 | Косметика: TODO: extract method for cleaner readability |

## Покрытие по репозиториям

| репо | всего | ранжировано |
|------|-------|-------------|
| grafana/grafana | 5 | 5 |
| grafana/mimir | 4 | 4 |
| grafana/loki | 3 | 3 |
| grafana/tempo | 3 | 3 |
| grafana/alloy | 3 | 3 |
| grafana/k6 | 2 | 2 |
