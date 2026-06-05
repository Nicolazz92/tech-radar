#!/usr/bin/env python3
"""score_tail.py — score markers with a transparent, text-aware rubric.

Severity anchors (1/3/9), derived from the wording of the marker itself:
  9  critical: security/auth bypass, data loss/corruption, resource leak,
     data race / deadlock, or an explicit "crashes/panics in prod" class.
  3  real: correctness/risk wording, a production HACK workaround, or a
     genuine missing implementation that surfaces on a real path.
  1  cosmetic: cleanup / refactor-note / optimization / configurability /
     documentation / test-only.

Emits a JSON array of {id, severity, fix_cost_h, rationale, description,
priority_argument, cross_repo_impact} on stdout — feed to rank.py --write-scores.
"""
import json, re, sys, pathlib

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parents[1]
rows = json.loads((ROOT / "output" / "score_view.json").read_text(encoding="utf-8"))

# --- severity-9 signals (kept specific to avoid false positives) -------------
# NOTE: matched with word boundaries (see kw_match) — bare substrings like
# "rce" must never match "souRCE"/"enfoRCE".
SEC9 = ["auth bypass", "authentication bypass", "authz bypass", "bypass auth",
        "bypass the check", "security hole", "vulnerability", "vulnerable",
        "exploit", "exploitable", "sql injection", "command injection", "xss",
        "csrf", "ssrf", "rce", "privilege escalation", "escalate privilege",
        "spoof", "spoofable", "secret leak", "token leak", "credential leak",
        "leak the secret", "leak the token", "insecure", "timing attack",
        "auth check", "missing auth"]
CRASH9 = ["will crash", "can crash", "crashes the", "will panic", "panics in",
          "segfault", "sigsegv", "data loss", "lose data", "loses data",
          "data corruption", "corrupt the", "corrupts", "drops data",
          "drop data", "silently drop"]
LEAK9 = ["memory leak", "mem leak", "goroutine leak", "fd leak",
         "file descriptor leak", "resource leak", "leaks memory",
         "leaks a goroutine", "connection leak"]
CONC9 = ["data race", "race condition", "deadlock", "dead-lock",
         "double free", "use after free", "use-after-free"]

# --- severity-3 / category signals -------------------------------------------
CORR = ["correctness", "bug", "not implemented", "panic", "always nil",
        "collision", "race", " leak", "incorrect", "not correct",
        "is this one correct", "overflow", "wrong value", "inflated",
        "this is always", "o(n*m)", "o(n*n)", "contention", "backpressure",
        "not entirely correct", "isn't entirely correct", "this check is not",
        "duplicate registration", "broken", "doesn't work", "does not work",
        "hack around", "workaround", "fragile", "brittle", "footgun"]
FEAT = ["implement", "add support", "integrate", "support native",
        "support histogram", "support start", "support created",
        "support stats", "download queue", "hasn't been implemented",
        "not yet", "track and report", "missing"]
PERF = ["efficient", "perf", "o(n", "allocation", "allocs", "pool",
        "benchmark", "expensive", "realloc", "reduce alloc", "loser-tree",
        "heap?", "lock", "improve allocations", "slow", "optimi"]
CONFIG = ["configurable", "allow configuration", "parameteris", "parameterise",
          "hedge config", "be configurable", "hardcoded", "hard-coded",
          "hard coded"]
DOC = ["add clear description", "add description", "clear description",
       "document this", "explain why", "add docs", "godoc"]
CLEAN = ["refactor", "clean up", "cleanup", "remove", "ugly", "rework",
         "simplif", "placeholder", "testware", "reuse", "derivable",
         "dismiss", "generic", "abstract", "better pattern", "pretty",
         "needless", "wrapper", "rename", "tidy", "dead code"]

CAT_LABEL = {
    "security":    "Безопасность / обход защиты",
    "crash":       "Краш / потеря данных",
    "leak":        "Утечка ресурсов",
    "concurrency": "Гонка / дедлок",
    "correctness": "Корректность / риск",
    "feature":     "Недостающая реализация",
    "perf":        "Производительность",
    "config":      "Конфигурируемость",
    "doc":         "Документация",
    "test":        "Тестовый код",
    "hack":        "Обходной хак (workaround)",
    "cleanup":     "Рефакторинг / чистота",
}

# what to do about it, per category — surfaced inside description
REMEDY = {
    "security":    "Требует аудита пути: закрыть обход, добавить регресс-тест "
                   "на сценарий атаки и алёрт на повторение.",
    "crash":       "Воспроизвести краш/потерю данных тестом, добавить защитную "
                   "проверку на границе и только потом править логику.",
    "leak":        "Подтвердить утечку профилем (pprof/heap), закрыть владение "
                   "ресурсом (defer/Close) и добавить тест на отсутствие роста.",
    "concurrency": "Зафиксировать гонку через -race, закрыть участок "
                   "синхронизацией/каналом, покрыть стресс-тестом.",
    "correctness": "Проверить инвариант и граничные случаи, зафиксировать "
                   "ожидаемое поведение тестом, затем поправить логику.",
    "feature":     "Допроектировать недостающую ветку поведения и покрыть её "
                   "тестом до включения в горячий путь.",
    "perf":        "Снять бенчмарк/профиль, подтвердить что путь горячий, затем "
                   "оптимизировать (пул, переиспользование буферов, аллокации).",
    "config":      "Вынести значение в конфиг с разумным дефолтом и валидацией, "
                   "убрать «магическую» константу.",
    "doc":         "Дописать контракт/поведение в комментарий или godoc, чтобы "
                   "снять неоднозначность для вызывающих.",
    "test":        "Заменить обходной приём на детерминированную фикстуру, чтобы "
                   "тест не зависел от случайного поведения.",
    "hack":        "Заменить обход штатным механизмом и убрать скрытую "
                   "связанность, чтобы изменения рядом не ломали поведение.",
    "cleanup":     "Локальный рефакторинг без изменения поведения, провести "
                   "под обычным ревью когда будете рядом.",
}

BR_RU = {"fan_out":   "fan-out — код вызывают из многих мест и тянут зависимые репо",
         "one_caller": "один вызыватель",
         "isolated":  "изолированный участок"}


def short_repo(r):
    return r.split("/", 1)[-1] if "/" in r else r


def clip(text, n):
    """Truncate to <= n chars without cutting a sentence in half.

    Prefers the last sentence boundary (". ") inside the budget; if none is
    reasonably far in, falls back to a word boundary + ellipsis so we never
    end mid-word.
    """
    text = (text or "").strip()
    if len(text) <= n:
        return text
    head = text[:n]
    dot = max(head.rfind(". "), head.rfind(".\n"))
    if dot >= int(n * 0.6):
        return head[:dot + 1].strip()
    sp = head.rfind(" ")
    return (head[:sp] if sp > 0 else head).rstrip(" ,;:—-") + "…"


def clean_body(txt):
    """Strip markdown/HTML noise from an issue body for display."""
    if not txt:
        return ""
    s = txt
    s = re.sub(r"<img[^>]*>", "", s, flags=re.I)      # image tags
    s = re.sub(r"<[^>]+>", "", s)                       # any other html
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)          # ![alt](url)
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)      # [text](url) -> text
    s = re.sub(r"https?://\S+", "", s)                  # bare urls
    s = re.sub(r"`{1,3}", "", s)                         # backticks/fences
    s = re.sub(r"^\s{0,3}#{1,6}\s*", "", s, flags=re.M)  # md headers
    s = re.sub(r"[*_>#]+", " ", s)                       # md emphasis/quote
    s = re.sub(r"\s+", " ", s)                           # collapse whitespace
    return s.strip()


def clean_note(txt):
    m = re.search(r"(TODO|FIXME|HACK|XXX)", txt)
    s = txt[m.end():] if m else txt
    s = re.sub(r"^\s*\([^)]*\)", "", s)      # strip (author)
    s = s.lstrip(" :>-)!.")
    return (s.strip() or "—")[:180]


def _has(txt, kws):
    # word-boundary match for alphanumeric phrases (so "rce" != "source");
    # plain substring for keywords containing punctuation like "o(n*m)".
    for kw in kws:
        if re.fullmatch(r"[a-z0-9 ]+", kw):
            if re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", txt):
                return True
        elif kw in txt:
            return True
    return False


def classify(r):
    txt = (r["txt"] or "").lower()
    marker = r["marker"]
    kind = r.get("kind", "inline_marker")
    labels = [str(l).lower() for l in (r.get("labels") or [])]
    is_test = "_test.go" in (r["loc"] or "")

    def has(kws):
        return _has(txt, kws)

    # ---- GitHub issues: labels carry explicit maintainer severity ----
    if kind == "issue":
        sec_label = any(("security" in l or "vuln" in l) for l in labels)
        bug_label = any((l in ("bug", "type/bug", "regression",
                                "type/regression") or l.endswith("/bug"))
                        for l in labels)
        debt_label = any("debt" in l for l in labels)
        # security feature-requests are hardening, not active critical defects
        enhancement = any(("feature" in l or "enhancement" in l) for l in labels)
        # explicit severity-9 classes still win on wording
        if has(CRASH9):
            return 9, "crash"
        if has(LEAK9):
            return 9, "leak"
        if has(CONC9):
            return 9, "concurrency"
        if has(SEC9):
            return 9, "security"
        if sec_label:
            # active security bug → 9; security hardening request → real (3)
            return (3, "security") if (enhancement and not bug_label) \
                else (9, "security")
        if bug_label:
            if has(PERF):
                return 3, "perf"
            if has(FEAT) and "not implemented" not in txt:
                return 3, "feature"
            return 3, "correctness"
        if debt_label:
            return (3, "hack") if (marker == "HACK" or has(CORR)) else (1, "cleanup")
        # labelled but neither security/bug/debt → triage by wording
        if has(CORR):
            return 3, "correctness"
        return 1, "cleanup"

    # ---- severity-9 tier first (highest signal) ----
    if not is_test and has(SEC9):
        return 9, "security"
    if not is_test and has(CRASH9):
        return 9, "crash"
    if not is_test and has(LEAK9):
        return 9, "leak"
    if not is_test and has(CONC9):
        return 9, "concurrency"

    # ---- category for sev 1/3 ----
    if is_test:
        cat = "test"
    elif has(DOC):
        cat = "doc"
    elif has(CORR):
        cat = "correctness"
    elif marker == "HACK":
        cat = "hack"
    elif has(FEAT):
        cat = "feature"
    elif has(PERF):
        cat = "perf"
    elif has(CONFIG):
        cat = "config"
    else:
        cat = "cleanup"

    if cat in ("test", "doc"):
        sev = 1
    elif cat == "correctness":
        sev = 3
    elif cat == "hack":
        sev = 3
    elif cat == "feature":
        sev = 3 if (marker in ("FIXME", "HACK")
                    or "not implemented" in txt or "panic" in txt) else 1
    else:
        sev = 1
    return sev, cat


def cost_for(cat, txt):
    base = {"security": 8, "crash": 8, "leak": 6, "concurrency": 8,
            "correctness": 4, "feature": 6, "perf": 3, "config": 2,
            "doc": 1, "test": 1, "hack": 3, "cleanup": 3}[cat]
    if re.search(r"refactor|rework|rewrite|generic|abstract|redesign", txt):
        base += 2
    return max(1, min(base, 16))


def severity_phrase(sev, cat):
    if sev == 9:
        return ("Это несущий дефект: автор прямо описывает класс проблемы, "
                "который ломает функциональность или открывает риск, а не "
                "косметику.")
    if sev == 3:
        if cat == "hack":
            return ("Это осознанный обход в рабочем коде — он работает, но "
                    "повышает хрупкость и риск регрессий при изменениях рядом.")
        if cat == "feature":
            return ("Это незакрытая ветка поведения: пока путь не задействован "
                    "плотно — терпимо, но всплывёт при росте использования.")
        return ("Это реальный, но не блокирующий дефект — из тех, что всплывают "
                "в PR-ревью и триаже.")
    return ("Это косметика/долговая заметка — не влияет на работу сейчас, "
            "ценность скорее в гигиене кода.")


out = []
for r in rows:
    sev, cat = classify(r)
    cost = cost_for(cat, (r["txt"] or "").lower())
    note = clean_note(r["txt"])
    label = CAT_LABEL[cat]
    fn = r.get("fn")
    sig = (r.get("sig") or "").strip()
    loc = r["loc"]
    imp = r.get("imp") or []
    br = r.get("br") or "isolated"
    exp = r.get("exp")
    age = r.get("age")
    author = r.get("author")

    kind = r.get("kind", "inline_marker")
    is_issue = kind == "issue"
    labels = [str(l) for l in (r.get("labels") or [])]

    where = f"функции `{fn}()`" if fn else f"`{loc.rsplit('/', 1)[-1]}`"
    vis = ("экспортируемой (часть публичного API пакета)" if exp
           else "внутренней") if fn else ""

    # ---------- description: multi-sentence, context-rich ----------
    if is_issue:
        title = (r.get("title") or note).strip()
        d = [f"GitHub issue {loc} в репозитории {short_repo(r['repo'])}: "
             f"«{title[:160]}»."]
        if labels:
            d.append("Лейблы мейнтейнеров: " + ", ".join(labels[:6]) + ".")
        body = clean_body(r.get("body") or "")
        if body:
            d.append("Суть: " + clip(body, 300))
        d.append(f"По классификации это «{label.lower()}». "
                 + severity_phrase(sev, cat))
        if age is not None:
            a = f"Тикет открыт ~{age} дн. назад"
            if author:
                a += f" (автор {author})"
            d.append(a + ".")
        d.append("Что делать: " + REMEDY[cat])
        description = clip(" ".join(d), 900)
    else:
        d = [f"{r['marker']}-маркер в репозитории {short_repo(r['repo'])}, "
             f"файл {loc}" + (f", в {vis} {where}." if fn else ".")]
        if sig:
            d.append(f"Сигнатура: `{sig}`.")
        d.append(f"Что отметил автор: «{note}».")
        d.append(f"По смыслу это «{label.lower()}». " + severity_phrase(sev, cat))
        # blast radius + named importers
        br_sentence = f"Радиус влияния — {BR_RU.get(br, br)}"
        if imp:
            names = ", ".join(short_repo(x) for x in imp)
            br_sentence += (f"; этот код импортируют {len(imp)} репо группы "
                            f"({names}), поэтому правка/регрессия отзовётся у них")
        d.append(br_sentence + ".")
        if age is not None:
            a = f"Маркер висит ~{age} дн."
            if author:
                a += f" (внёс {author})"
            d.append(a + ".")
        d.append("Что делать: " + REMEDY[cat])
        description = clip(" ".join(d), 900)

    # ---------- rationale: compact one-liner for the grid ----------
    if is_issue:
        lab_short = ", ".join(labels[:3]) if labels else "issue"
        rationale = (f"{label}. Открытый тикет ({lab_short})"
                     + (f", ~{age} дн." if age is not None else "") + ".")[:240]
    else:
        rationale = (f"{label}. {BR_RU.get(br, br).split('—')[0].strip()}"
                     + (f", тянут {len(imp)} репо" if imp else "")
                     + (". Экспортируемая ф-я" if exp else "") + ".")[:240]

    # ---------- priority_argument: why this rank, what if ignored ----------
    if is_issue and sev == 9:
        prio = (f"Высокий приоритет. Мейнтейнеры пометили тикет как "
                f"{label.lower()} — класс, который реально бьёт по проде "
                f"(безопасность/краш/гонка/утечка). Брать в ближайший спринт, "
                f"не откладывать в долг.")
    elif is_issue and sev == 3:
        prio = (f"Средний приоритет. Подтверждённый мейнтейнерами дефект "
                f"({label.lower()}); всплывает у пользователей, но не блокирует "
                f"критичный путь. Планировать в ближайшие итерации.")
    elif is_issue:
        prio = (f"Низкий приоритет. {label} из бэклога — гигиена/долг, "
                f"закрывать по мере ёмкости команды.")
    elif sev == 9:
        prio = (f"Высокий приоритет. Если оставить как есть, риск реализуется в "
                f"проде ({label.lower()}) и затронет "
                + (f"{len(imp)} зависимых репо группы." if imp
                   else "пользователей этого пути.")
                + " Брать в ближайший спринт, не откладывать в долг.")
    elif sev == 3 and cat == "hack":
        prio = (f"Средний приоритет. Обход в {where} держится на неявных "
                f"допущениях; при доработке соседнего кода легко получить "
                f"скрытую регрессию. Закрывать при первом касании этого модуля.")
    elif sev == 3 and cat == "correctness":
        prio = (f"Средний приоритет. Формулировка указывает на возможную "
                f"некорректность в {where}; "
                + ("учитывая fan-out, цена ошибки умножается на зависимые репо. "
                   if br == "fan_out" else "")
                + "Стоит проверить инвариант и закрыть тестом.")
    elif sev == 3 and cat == "feature":
        prio = (f"Средний приоритет. Недостающая реализация в {where} безопасна, "
                f"пока путь редкий, но станет дефектом при росте нагрузки на эту "
                f"ветку. Планировать вместе с фичей, которая её активирует.")
    else:
        prio = (f"Низкий приоритет. {label} в {where} не влияет на работу и не "
                f"блокирует; разумно закрыть попутно при работе рядом, отдельный "
                f"тикет заводить не обязательно.")
    prio = clip(prio, 700)

    out.append({
        "id": r["id"],
        "severity": sev,
        "fix_cost_h": cost,
        "rationale": rationale,
        "description": description,
        "priority_argument": prio,
        "cross_repo_impact": imp,
    })

from collections import Counter
sys.stderr.write("sev dist: %s\n" % dict(Counter(o["severity"] for o in out)))
sys.stderr.write("count: %d\n" % len(out))
sys.stdout.write(json.dumps(out, ensure_ascii=False))
