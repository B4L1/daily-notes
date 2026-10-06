import { cellColor, signMark, fmtPct, fmtUsd, calendarCells, luckText } from "./lib.js";
import { lineChart, sparkline } from "./charts.js";

const COLORS = ["#58a6ff", "#d29922", "#3fb950", "#bc8cff", "#f778ba", "#39c5cf", "#ff7b72", "#ffa657", "#7ee787", "#a5d6ff"];
const CONTROL_COLOR = "#6e7681";
const PNL_SCALE = 0.02;
const HIT_SCALE = 0.5;
const HEAT_DAYS = 90;

const store = (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } };
const keep = (k, v) => { try { localStorage.setItem(k, v); } catch { /* storage unavailable: fine */ } };

const state = { mode: store("mode", "live"), palette: store("palette", "default"), summary: null, detail: {} };

export function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  n.append(...kids.filter((x) => x !== null && x !== undefined));
  return n;
}

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${url} ${r.status}`);
  return r.json();
}

const meta = () => Object.fromEntries(state.summary.estimators.map((e) => [e.name, e]));
const block = () => state.summary.modes[state.mode];

function colorMap() {
  const out = {};
  let i = 0;
  for (const e of state.summary.estimators) out[e.name] = e.kind === "control" ? CONTROL_COLOR : COLORS[i++ % COLORS.length];
  return out;
}

function trend(v) { return v > 0 ? "up" : v < 0 ? "down" : "flat"; }

function badges(r) {
  const out = [];
  if (r.status !== "ok" && r.status !== "no_run") out.push(el("span", { class: "badge bad" }, r.status.replace("_", " ")));
  if (r.sanity) out.push(el("span", { class: "badge" }, "check this"));
  return out;
}

function panel(title, text) {
  return el("div", { class: "panel" }, el("h3", {}, title), el("p", { class: "dim" }, text));
}

function showError(message, retry) {
  const view = document.getElementById("view");
  view.textContent = "";
  view.append(el("div", { class: "panel" }, el("p", { class: "warn" }, message), el("button", { type: "button", onclick: retry }, "Retry")));
}

function heatGrid(b, names, key, scale) {
  const m = meta();
  const dates = b.dates.slice(-HEAT_DAYS);
  const offset = b.dates.length - dates.length;
  const label = key === "hit" ? "Heatmap of direction hit rate per day" : "Heatmap of daily account return";
  const wrap = el("div", { class: "heat", role: "img", "aria-label": `${label}. The same numbers are in the leaderboard and on each estimator's tab.` });
  for (const n of names) {
    const cells = el("div", { class: "heat-cells" });
    dates.forEach((d, i) => {
      const v = b[key][n][offset + i];
      const dev = key === "hit" && v !== null ? v - 0.5 : v;
      const text = v === null ? `${d}: no calls` : key === "hit" ? `${d}: ${signMark(dev)} ${(v * 100).toFixed(0)}% correct` : `${d}: ${signMark(v)} ${fmtPct(v)}`;
      cells.append(el("div", { class: "cell", title: text, style: `background:${cellColor(dev, scale, state.palette)}` }));
    });
    wrap.append(el("div", { class: "heat-row" }, el("span", { class: "heat-label" }, m[n].label), cells));
  }
  return wrap;
}

function renderOverview(view) {
  const m = meta();
  const colors = colorMap();
  const b = block();
  const names = state.summary.estimators.map((e) => e.name);
  const active = names.filter((n) => b.rows[n].n_days > 0);
  const stale = Object.entries(state.summary.stale_assets);

  if (state.mode === "backtest") {
    view.append(el("p", { class: "note" }, "Backtest: every day replayed using only earlier data. Pretrained models may have seen this period in training, so their backtest numbers may be optimistic. Live results are the real verdict."));
  }
  if (stale.length) {
    view.append(el("p", { class: "warn" }, "Stale data: " + stale.map(([s, g]) => (g === null ? `${s} (no data)` : `${s} (${g} days behind)`)).join(", ")));
  }
  if (!active.length) {
    view.append(panel(
      state.mode === "live" ? "No settled days yet" : "No backtest data yet",
      state.mode === "live"
        ? "Predictions are being logged. The first results appear after the next trading session closes."
        : "Run the backfill workflow to fill in the past year."
    ));
    return;
  }

  view.append(el("h2", {}, "Wallets"));
  const strip = el("div", { class: "strip" });
  for (const n of [...active].sort((a, c) => b.rows[c].balance - b.rows[a].balance)) {
    const r = b.rows[n];
    strip.append(el("a", { class: "tile", href: `#/e/${n}`, style: `color:${colors[n]}` },
      el("div", { class: "tile-name" }, m[n].label),
      el("div", { class: "tile-bal", style: "color:var(--text)" }, fmtUsd(r.balance)),
      el("div", { class: trend(r.day_return) }, `${signMark(r.day_return)} ${fmtPct(r.day_return)}  (${r.day_change >= 0 ? "+" : "-"}${fmtUsd(Math.abs(r.day_change))})`),
      sparkline(r.spark),
      el("div", {}, ...badges(r))));
  }
  view.append(strip);

  view.append(el("h2", {}, "Account value"));
  const chart = el("div", {});
  view.append(chart);
  const series = active.map((n) => ({ name: m[n].label, color: colors[n], dashed: m[n].kind === "control", points: b.equity[n] }));
  series.push({ name: "Buy and hold (reference, no costs)", color: "#8b949e", dashed: true, points: b.hold });
  lineChart(chart, series);

  view.append(el("h2", {}, "Leaderboard"));
  const head = ["Estimator", "Balance", "Return", "Edge vs random", "Hit", "Down calls hit", "Max drawdown", "Worst day", "Trades/day", "Luck check", "Status"];
  const rows = names.map((n) => {
    const r = b.rows[n];
    const hit = (v) => (v === null ? "n/a" : (v * 100).toFixed(1) + "%");
    return el("tr", {},
      el("td", {}, el("a", { href: `#/e/${n}`, style: "color:inherit" }, m[n].label)),
      el("td", {}, fmtUsd(r.balance)),
      el("td", { class: trend(r.total_return) }, `${signMark(r.total_return)} ${fmtPct(r.total_return)}`),
      el("td", {}, m[n].kind === "control" ? "baseline" : fmtPct(r.edge, 3)),
      el("td", {}, hit(r.hit_rate)), el("td", {}, hit(r.hit_rate_down)),
      el("td", {}, fmtPct(r.max_drawdown)), el("td", {}, fmtPct(r.worst_day)),
      el("td", {}, r.trades_per_day.toFixed(1)),
      el("td", {}, m[n].kind === "control" ? "baseline" : luckText(r)),
      el("td", {}, ...badges(r), r.status === "ok" ? "ok" : r.status === "no_run" ? "not run yet" : ""));
  });
  view.append(el("div", { class: "tablewrap" }, el("table", {}, el("thead", {}, el("tr", {}, ...head.map((h) => el("th", {}, h)))), el("tbody", {}, ...rows))));
  view.append(el("p", { class: "note" }, "Edge is the average daily return minus the random control's. Trades/day near 0 means the estimator mostly stayed in cash."));

  view.append(el("h2", {}, "Daily account return (last 90 days)"));
  view.append(heatGrid(b, active, "pnl", PNL_SCALE));
  view.append(el("h2", {}, "Direction hit rate per day (last 90 days)"));
  view.append(heatGrid(b, active, "hit", HIT_SCALE));
  view.append(el("p", { class: "note" }, "Brighter means bigger. For hit rate, bright green is mostly right, bright red mostly wrong, and dim is about 50%."));
}

function renderTabs(route) {
  const tabs = document.getElementById("tabs");
  tabs.textContent = "";
  const link = (href, text, current) => el("a", { href, "aria-current": current ? "page" : undefined }, text);
  tabs.append(link("#/", "Overview", !route.startsWith("e/")));
  for (const e of state.summary.estimators) tabs.append(link(`#/e/${e.name}`, e.label, route === `e/${e.name}`));
}

export function render() {
  const route = location.hash.replace(/^#\/?/, "");
  const view = document.getElementById("view");
  view.textContent = "";
  document.querySelectorAll("[data-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === state.mode)));
  if (!state.summary) return;
  renderTabs(route);
  if (route.startsWith("e/")) return renderEstimator(view, decodeURIComponent(route.slice(2)));
  renderOverview(view);
}

// Replaced in Task 11.
function renderEstimator(view, name) {
  view.append(panel(name, "This tab is built in the next task."));
}

function applyPalette() {
  document.documentElement.dataset.palette = state.palette;
  document.getElementById("palette").setAttribute("aria-pressed", String(state.palette === "cvd"));
}

async function boot() {
  applyPalette();
  try {
    state.summary = await getJSON("data/summary.json");
  } catch {
    return showError("Couldn't load the data. Check your connection, then retry.", boot);
  }
  render();
}

document.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => {
  state.mode = b.dataset.mode; keep("mode", state.mode); render();
}));
document.getElementById("palette").addEventListener("click", () => {
  state.palette = state.palette === "cvd" ? "default" : "cvd"; keep("palette", state.palette); applyPalette(); render();
});
window.addEventListener("hashchange", () => { render(); document.getElementById("view").focus(); });
boot();
