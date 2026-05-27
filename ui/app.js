"use strict";

const PRIORITY_TEXT = { 9: "high", 6: "high", 3: "medium", 1: "low" };

const state = {
  raw: null,
  items: [],
  filters: { severity: "all", kind: "all", search: "" },
  sort: { key: "impact", dir: "desc" },
  selectedId: null,
};

// ------------------------------------------------------------ utils

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function shortRepo(repo) {
  return repo && repo.includes("/") ? repo.split("/")[1] : repo || "";
}

function fmtImpact(v) {
  if (v == null) return "—";
  return Number(v).toFixed(1);
}

function fmtTs(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("ru-RU", {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit",
    });
  } catch (e) {
    return iso;
  }
}

function severityBadge(sev) {
  if (sev == null) return `<span class="badge badge-0">—</span>`;
  return `<span class="badge badge-${sev}">${sev}</span>`;
}

function kindBadge(kind) {
  if (kind === "inline_marker") return `<span class="badge badge-kind-inline">inline</span>`;
  if (kind === "issue") return `<span class="badge badge-kind-issue">issue</span>`;
  return `<span class="badge badge-0">${kind || "?"}</span>`;
}

function priorityText(item) {
  const p = item.priority_label ?? item.severity ?? 1;
  return PRIORITY_TEXT[p] || String(p);
}

function locatorCell(item) {
  if (item.kind === "issue") {
    const url = item.locator || "";
    const n = item.number;
    const label = n ? `#${n}` : url;
    return `<span class="cell-loc"><a href="${url}" target="_blank" rel="noopener">${label}</a></span>`;
  }
  return `<span class="cell-loc">${escapeHtml(item.locator || "")}</span>`;
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// ------------------------------------------------------------ data load

async function load() {
  const resp = await fetch("inventory.json", { cache: "no-cache" });
  if (!resp.ok) throw new Error(`inventory.json: HTTP ${resp.status}`);
  state.raw = await resp.json();
  state.items = state.raw.items || [];
  renderAll();
}

// ------------------------------------------------------------ filters

function applyFilters(items) {
  const { severity, kind, search } = state.filters;
  return items.filter((it) => {
    if (severity !== "all") {
      if (severity === "null") {
        if (it.severity != null) return false;
      } else {
        if (String(it.severity) !== severity) return false;
      }
    }
    if (kind !== "all" && it.kind !== kind) return false;
    if (search) {
      const s = search.toLowerCase();
      const hay = [
        it.title_or_excerpt, it.locator, it.repo, it.rationale,
        it.description, it.priority_argument,
        (it.labels || []).join(" "),
      ].filter(Boolean).join(" ").toLowerCase();
      if (!hay.includes(s)) return false;
    }
    return true;
  });
}

function applySort(items) {
  const { key, dir } = state.sort;
  const mul = dir === "asc" ? 1 : -1;
  const get = (it) => {
    if (key === "impact") return it.impact == null ? -1 : it.impact;
    if (key === "severity") return it.severity == null ? -1 : it.severity;
    if (key === "fix_cost_h") return it.fix_cost_h == null ? Infinity : it.fix_cost_h;
    if (key === "priority") return it.priority_label == null ? 0 : it.priority_label;
    if (key === "repo") return shortRepo(it.repo);
    if (key === "kind") return it.kind || "";
    return "";
  };
  return [...items].sort((a, b) => {
    const av = get(a), bv = get(b);
    if (av < bv) return -1 * mul;
    if (av > bv) return 1 * mul;
    return 0;
  });
}

// ------------------------------------------------------------ rendering

function renderAll() {
  renderMeta();
  renderCharts();
  renderGrid();
}

function renderMeta() {
  const stats = (state.raw && state.raw.stats) || {};
  $("#m-total").textContent = stats.items_total ?? 0;
  $("#m-ranked").textContent = stats.ranked_count ?? 0;
  $("#m-formula").textContent = stats.formula_version || "—";
  const rr = stats.ranking_run || {};
  $("#m-model").textContent = rr.model || "—";
  $("#m-ts").textContent = fmtTs(state.raw && state.raw.ts);
}

function renderCharts() {
  // by severity
  const sevBuckets = { 9: 0, 3: 0, 1: 0, null: 0 };
  for (const it of state.items) {
    const k = it.severity == null ? "null" : it.severity;
    if (k in sevBuckets) sevBuckets[k] += 1;
  }
  renderBars($("#chart-severity"), [
    { label: "9 — несущий", value: sevBuckets[9], cls: "sev9" },
    { label: "3 — реальный", value: sevBuckets[3], cls: "sev3" },
    { label: "1 — косметика", value: sevBuckets[1], cls: "sev1" },
    { label: "без оценки", value: sevBuckets["null"], cls: "sev0" },
  ]);
  // by repo
  const repoBuckets = {};
  for (const it of state.items) {
    const r = shortRepo(it.repo);
    repoBuckets[r] = (repoBuckets[r] || 0) + 1;
  }
  const rows = Object.entries(repoBuckets)
    .sort((a, b) => b[1] - a[1])
    .map(([r, n]) => ({ label: r, value: n, cls: "" }));
  renderBars($("#chart-repos"), rows);
}

function renderBars(container, rows) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  container.innerHTML = "";
  for (const row of rows) {
    const pct = (row.value / max) * 100;
    const div = document.createElement("div");
    div.className = "bar-row";
    div.innerHTML = `
      <div class="bar-label" title="${escapeHtml(row.label)}">${escapeHtml(row.label)}</div>
      <div class="bar-track"><div class="bar-fill ${row.cls}" style="width: ${pct}%"></div></div>
      <div class="bar-value">${row.value}</div>
    `;
    container.appendChild(div);
  }
}

function renderGrid() {
  const filtered = applyFilters(state.items);
  const sorted = applySort(filtered);

  $("#visible-count").textContent = filtered.length;
  $("#total-count").textContent = state.items.length;
  $("#empty").classList.toggle("hidden", filtered.length > 0);

  const tbody = $("#grid-body");
  tbody.innerHTML = "";
  for (let i = 0; i < sorted.length; i++) {
    const it = sorted[i];
    const tr = document.createElement("tr");
    if (it.id === state.selectedId) tr.classList.add("selected");
    tr.dataset.id = it.id;
    tr.innerHTML = `
      <td class="num">${i + 1}</td>
      <td>${escapeHtml(shortRepo(it.repo))}</td>
      <td>${kindBadge(it.kind)}</td>
      <td>${locatorCell(it)}</td>
      <td>${escapeHtml(priorityText(it))}</td>
      <td class="num">${severityBadge(it.severity)}</td>
      <td class="num">${it.fix_cost_h == null ? "—" : it.fix_cost_h}</td>
      <td class="cell-links">${escapeHtml((it.links || []).map(shortRepo).join(", ") || "—")}</td>
      <td class="num">${fmtImpact(it.impact)}</td>
      <td><div class="cell-rationale">${escapeHtml(it.rationale || "—")}</div></td>
    `;
    tr.addEventListener("click", (e) => {
      // Don't open drawer when clicking a link inside the row
      if (e.target.tagName === "A") return;
      openDrawer(it);
    });
    tbody.appendChild(tr);
  }
}

// ------------------------------------------------------------ drawer

function openDrawer(it) {
  state.selectedId = it.id;
  $("#dr-title").textContent = it.title_or_excerpt || it.title || it.locator || it.id;
  $("#dr-repo").textContent = it.repo;
  $("#dr-locator").innerHTML = locatorCell(it);
  $("#dr-sev").innerHTML = severityBadge(it.severity);
  $("#dr-cost").textContent = it.fix_cost_h == null ? "—" : `${it.fix_cost_h} ч`;
  $("#dr-impact").textContent = fmtImpact(it.impact);
  $("#dr-links").textContent = (it.links || []).map(shortRepo).join(", ") || "—";
  $("#dr-rat").textContent = it.rationale || "—";
  $("#dr-desc").textContent = it.description || "—";
  $("#dr-prio").textContent = it.priority_argument || "—";
  const lab = $("#dr-labels");
  lab.innerHTML = "";
  for (const l of (it.labels || [])) {
    const span = document.createElement("span");
    span.className = "label-pill";
    span.textContent = l;
    lab.appendChild(span);
  }
  if (!(it.labels && it.labels.length)) {
    const span = document.createElement("span");
    span.className = "label-pill";
    span.textContent = "—";
    lab.appendChild(span);
  }
  $("#drawer").classList.remove("hidden");
  renderGrid();
}

function closeDrawer() {
  state.selectedId = null;
  $("#drawer").classList.add("hidden");
  renderGrid();
}

// ------------------------------------------------------------ wire up

function wireFilters() {
  $$(".filter-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const f = btn.dataset.filter;
      const v = btn.dataset.value;
      state.filters[f] = v;
      $$(`.filter-btn[data-filter="${f}"]`).forEach((b) => b.classList.toggle("active", b === btn));
      renderGrid();
    });
  });
  $("#search").addEventListener("input", (e) => {
    state.filters.search = e.target.value.trim();
    renderGrid();
  });
}

function wireSort() {
  $$("#grid thead th[data-sort]").forEach((th) => {
    th.addEventListener("click", (e) => {
      // Don't trigger sort when clicking the info-tip "?" button or anything inside its tooltip
      if (e.target.closest(".tip-wrap")) return;
      const key = th.dataset.sort;
      if (state.sort.key === key) {
        state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc";
      } else {
        state.sort.key = key;
        state.sort.dir = "desc";
      }
      $$("#grid thead th").forEach((t) => {
        t.classList.remove("sorted-asc", "sorted-desc");
      });
      th.classList.add(state.sort.dir === "asc" ? "sorted-asc" : "sorted-desc");
      renderGrid();
    });
  });
}

function wireDrawer() {
  $("#dr-close").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDrawer();
  });
}

// ------------------------------------------------------------ boot

(async function () {
  wireFilters();
  wireSort();
  wireDrawer();
  try {
    await load();
  } catch (e) {
    $("#grid-body").innerHTML = `<tr><td colspan="10" class="empty">
      Не удалось загрузить inventory.json: ${escapeHtml(e.message)}.
      Запустите <code>python radar.py --demo</code> сначала.
    </td></tr>`;
  }
})();
