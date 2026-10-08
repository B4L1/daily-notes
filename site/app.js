import { cellColor, signMark, fmtPct, fmtUsd, calendarCells, luckText, hitDeviation, dayHit,
  testedCount, staleness, freshnessText, updatedLine, validPalette, tickerItems, easeSpeed, strideNote, HOLD_LABEL } from "./lib.js";
import { lineChart, sparkline } from "./charts.js";

const COLORS = ["#58a6ff", "#d29922", "#3fb950", "#bc8cff", "#f778ba", "#39c5cf", "#ff7b72", "#ffa657", "#7ee787", "#a5d6ff"];
const CONTROL_COLOR = "#6e7681";
const PNL_SCALE = 0.02;
const HIT_SCALE = 0.5;
const HEAT_DAYS = 90;

const store = (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } };
const keep = (k, v) => { try { localStorage.setItem(k, v); } catch { /* storage unavailable: fine */ } };

const storedMode = store("mode", "live");
const state = { mode: storedMode === "backtest" ? "backtest" : "live", palette: validPalette(store("palette", "default")), summary: null, detail: {} };

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
const nTests = () => testedCount(state.summary.estimators);

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

let loadError = false;
function showError(message, retry) {
  loadError = true;
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
      const dev = key === "hit" ? hitDeviation(v) : v;
      const text = v === null || v === undefined ? `${d}: ${key === "hit" ? "no calls" : "no data"}` : key === "hit" ? `${d}: ${signMark(dev)} ${(v * 100).toFixed(0)}% correct` : `${d}: ${signMark(v)} ${fmtPct(v)}`;
      cells.append(el("div", { class: "cell", title: text, style: `background:${cellColor(dev, scale, state.palette)}` }));
    });
    const vals = b[key][n].slice(offset).filter((x) => x !== null && x !== undefined);
    const avg = vals.length ? vals.reduce((a, c) => a + c, 0) / vals.length : null;
    const summary = vals.length
      ? `${m[n].label}: ${vals.length} days with data, average ${key === "hit" ? (avg * 100).toFixed(1) + "% correct" : fmtPct(avg)}`
      : `${m[n].label}: no data`;
    wrap.append(el("div", { class: "heat-row" }, el("span", { class: "heat-label", title: m[n].label }, m[n].label), el("span", { class: "sr-only" }, summary), cells));
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
  for (const n of [...active].sort((a, c) => (b.rows[c].balance ?? 0) - (b.rows[a].balance ?? 0))) {
    const r = b.rows[n];
    strip.append(el("a", { class: "tile", href: `#/e/${n}`, style: `color:${colors[n]}` },
      el("div", { class: "tile-name" }, m[n].label),
      state.mode === "backtest" && strideNote(m[n]) ? el("div", { class: "badge" }, strideNote(m[n])) : null,
      el("div", { class: "tile-bal", style: "color:var(--text)" }, fmtUsd(r.balance)),
      el("div", { class: trend(r.day_return) }, `${signMark(r.day_return)} ${fmtPct(r.day_return)}  (${r.day_change == null ? "n/a" : (r.day_change >= 0 ? "+" : "-") + fmtUsd(Math.abs(r.day_change))})`),
      sparkline(r.spark ?? []),
      el("div", {}, ...badges(r))));
  }
  view.append(strip);

  view.append(el("h2", {}, "Account value"));
  const chart = el("div", {});
  view.append(chart);
  const series = active.map((n) => ({ name: m[n].label, color: colors[n], dashed: m[n].kind === "control", points: b.equity[n] ?? [] }));
  series.push({ name: HOLD_LABEL, color: "#8b949e", dashed: true, points: b.hold ?? [] });
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
      el("td", {}, (r.trades_per_day == null ? "n/a" : r.trades_per_day.toFixed(1))),
      el("td", {}, m[n].kind === "control" ? "baseline" : luckText(r, nTests())),
      el("td", {}, ...badges(r), state.mode === "backtest" && strideNote(m[n]) ? strideNote(m[n]) + " " : "", r.status === "ok" ? "ok" : r.status === "no_run" ? "not run yet" : ""));
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

function renderFreshness(view) {
  const f = staleness(state.summary.generated_at, new Date());
  const footer = document.getElementById("freshness");
  if (footer) footer.textContent = freshnessText(state.summary);
  const top = document.getElementById("updated");
  if (top) top.textContent = updatedLine(state.summary);
  if (!f.stale) return;
  const age = f.ageHours === null ? "its age is unknown" : `it is ${Math.floor(f.ageHours)} hours old`;
  view.append(el("div", { class: "panel warn", role: "alert" },
    el("h3", {}, "Data may be out of date"),
    el("p", {}, `${freshnessText(state.summary)}; ${age}. The daily run may have failed or been skipped; check the Actions tab.`)));
}

export function render() {
  const route = location.hash.replace(/^#\/?/, "");
  const view = document.getElementById("view");
  view.textContent = "";
  document.querySelectorAll("[data-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === state.mode)));
  if (!state.summary) {
    if (loadError) showError("Couldn't load the data. Check your connection, then retry.", boot);
    return;
  }
  renderTabs(route);
  renderFreshness(view);
  if (route.startsWith("e/")) {
    let name;
    try { name = decodeURIComponent(route.slice(2)); } catch { name = null; }
    if (name === null) { view.append(panel("Unknown estimator", "That address isn't valid.")); return; }
    return renderEstimator(view, name);
  }
  renderOverview(view);
}

const hitText = (v) => (v === null || v === undefined ? "n/a" : (v * 100).toFixed(1) + "%");

function calendar(days, valueOf, scale, kind, devOf, describe) {
  const byDate = Object.fromEntries(days.map((d) => [d.date, valueOf(d)]));
  const cells = calendarCells(days.map((d) => d.date));
  const grid = el("div", { class: "cal", role: "img", "aria-label": `Calendar heatmap of ${kind}. The day list below has the same numbers.` });
  cells.forEach((c, i) => {
    const v = byDate[c.date] ?? null;
    const dev = devOf(v);
    const text = v === null ? `${c.date}: no session or no calls` : `${c.date}: ${describe(v, dev)}`;
    grid.append(el("div", { class: "cell", title: text, style: `background:${cellColor(dev, scale, state.palette)};${i === 0 ? `grid-row:${c.row + 1};` : ""}` }));
  });
  return grid;
}

function statsPanel(s, kind) {
  const items = [
    ["Balance", fmtUsd(s.balance)], ["Return", `${signMark(s.total_return)} ${fmtPct(s.total_return)}`],
    ["Days settled", String(s.n_days)], ["Hit rate", hitText(s.hit_rate)], ["Down calls hit", hitText(s.hit_rate_down)],
    ["Max drawdown", fmtPct(s.max_drawdown)], ["Worst day", fmtPct(s.worst_day)], ["Trades per day", s.trades_per_day == null ? "n/a" : s.trades_per_day.toFixed(1)],
    ["Luck check", kind === "control" ? "baseline" : luckText(s, nTests())],
  ];
  return el("div", { class: "stats" }, ...items.map(([k, v]) => el("div", { class: "stat" }, el("span", { class: "dim" }, k), el("b", {}, v))));
}

function assetTable(perAsset) {
  const rows = Object.entries(perAsset).sort((a, b) => b[1].net_return_sum - a[1].net_return_sum);
  return el("div", { class: "tablewrap" }, el("table", {},
    el("thead", {}, el("tr", {}, ...["Asset", "Calls", "Traded", "Hit", "Sum of trade returns"].map((h) => el("th", {}, h)))),
    el("tbody", {}, ...rows.map(([a, p]) => el("tr", {}, el("td", {}, a), el("td", {}, String(p.n)), el("td", {}, String(p.traded)), el("td", {}, hitText(p.hit_rate)), el("td", { class: trend(p.net_return_sum) }, `${signMark(p.net_return_sum)} ${fmtPct(p.net_return_sum)}`))))));
}

function dayList(days, isControl) {
  const wrap = el("div", {});
  const draw = (limit) => {
    wrap.textContent = "";
    for (const d of [...days].reverse().slice(0, limit)) {
      const trades = el("div", { class: "tablewrap" }, el("table", {},
        el("thead", {}, el("tr", {}, ...["Asset", "Predicted", "Actual", "Hit", "Traded", "Net return"].map((h) => el("th", {}, h)))),
        el("tbody", {}, ...d.trades.map((t) => el("tr", {},
          el("td", {}, t.asset),
          el("td", {}, isControl ? (t.expected_return > 0 ? "▲ long" : "▼ down") : `${signMark(t.expected_return)} ${fmtPct(t.expected_return)}`),
          el("td", {}, `${signMark(t.actual_cc)} ${fmtPct(t.actual_cc)}`),
          el("td", {}, t.hit === null || t.hit === undefined ? "n/a" : t.hit ? "yes" : "no"),
          el("td", {}, t.traded ? "yes" : "no (cash)"),
          el("td", { class: trend(t.net_ret) }, `${signMark(t.net_ret)} ${fmtPct(t.net_ret)}`))))));
      wrap.append(el("details", { class: "day" },
        el("summary", {}, el("span", {}, d.date), el("span", { class: trend(d.day_return) }, `${signMark(d.day_return)} ${fmtPct(d.day_return)}`), el("span", { class: "dim" }, `${fmtUsd(d.equity)} · ${d.n_traded} of ${d.n_universe} traded`)),
        trades));
    }
    if (days.length > limit) wrap.append(el("button", { type: "button", onclick: () => draw(days.length) }, `Show all ${days.length} days`));
  };
  draw(30);
  return wrap;
}

async function renderEstimator(view, name) {
  const startHash = location.hash;
  const m = state.summary.estimators.find((e) => e.name === name);
  if (!m) { view.append(panel("Unknown estimator", `There is no estimator called ${name}.`)); return; }
  view.append(el("p", { class: "dim" }, "Loading…"));
  let d = state.detail[name];
  if (!d) {
    try {
      d = state.detail[name] = await getJSON(`data/estimators/${name}.json`);
    } catch {
      if (location.hash !== startHash) return;
      return showError(`Couldn't load ${m.label}. Check your connection, then retry.`, render);
    }
  }
  if (location.hash !== startHash) return; // the user already moved on
  const mode = d?.modes?.[state.mode];
  const okShape = mode && Array.isArray(mode.days) && Array.isArray(mode.equity) && mode.stats && typeof mode.stats === "object" && mode.per_asset && typeof mode.per_asset === "object"
    && mode.days.every((x) => x && Array.isArray(x.trades));
  if (!okShape) {
    delete state.detail[name];
    return showError(`The data for ${m.label} looks damaged. Retry, or check back after the next update.`, render);
  }
  view.textContent = "";
  const isControl = m.kind === "control";
  view.append(el("h2", {}, m.label));
  view.append(el("p", { class: "dim" }, `${m.kind} · ${m.source} · licence: ${m.license} · ${m.original_code ? "original code" : "our own implementation"}`));
  if (state.mode === "backtest") view.append(el("p", { class: "note" }, "Backtest: each day replayed using only earlier data. Pretrained models may have seen this period in training, so their backtest numbers may be optimistic."));
  if (state.mode === "backtest" && strideNote(m)) view.append(el("p", { class: "warn" }, strideNote(m)));
  if (!mode.days.length) {
    view.append(panel(state.mode === "live" ? "No settled days yet" : "No backtest data yet", state.mode === "live" ? "Its predictions are being logged. Results appear after the next trading session closes." : "Run the backfill workflow to fill in the past year."));
    return;
  }
  view.append(el("h2", {}, "Summary"), statsPanel(mode.stats, m.kind));
  if (mode.stats.sanity) view.append(el("p", { class: "warn" }, "check this: a gain this large is more likely a bug or a data leak than skill."));

  view.append(el("h2", {}, "Account value"));
  const chart = el("div", {});
  view.append(chart);
  const b = block();
  const series = [{ name: m.label, color: "#58a6ff", dashed: false, points: mode.equity }];
  if (name !== "control_random") series.push({ name: "Random coin (control)", color: CONTROL_COLOR, dashed: true, points: b.equity.control_random ?? [] });
  series.push({ name: HOLD_LABEL, color: "#8b949e", dashed: true, points: b.hold ?? [] });
  lineChart(chart, series);

  view.append(el("h2", {}, "Daily account return"), calendar(mode.days, (x) => x.day_return, PNL_SCALE, "daily return", (v) => v, (v) => `${signMark(v)} ${fmtPct(v)}`));
  view.append(el("h2", {}, "Direction hit rate"), calendar(mode.days, dayHit, HIT_SCALE, "hit rate", hitDeviation, (v, dev) => `${signMark(dev)} ${(v * 100).toFixed(0)}% correct`));
  view.append(el("p", { class: "note" }, "Each square is one calendar day, oldest at the left. Empty squares are days with no session or no calls."));
  view.append(el("h2", {}, "By asset"), assetTable(mode.per_asset));
  view.append(el("h2", {}, "Day by day"), dayList(mode.days, isControl));
}

const TICKER_LOOP_SECONDS = 50;
const TICKER_TAU = 0.25;
const ticker = { raf: 0, offset: 0, speed: 1, last: 0, held: new Set(), track: null };
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

function tickerFrame(now) {
  ticker.raf = 0;
  const track = ticker.track;
  if (!track || reducedMotion.matches || document.hidden) return;
  const dt = ticker.last ? Math.min((now - ticker.last) / 1000, 0.1) : 0;
  ticker.last = now;
  ticker.speed = easeSpeed(ticker.speed, ticker.held.size ? 0 : 1, dt, TICKER_TAU);
  const half = track.scrollWidth / 2;
  if (half > 0) {
    ticker.offset = (ticker.offset + (half / TICKER_LOOP_SECONDS) * ticker.speed * dt) % half;
    track.style.transform = `translate3d(${(-ticker.offset).toFixed(2)}px,0,0)`;
  }
  ticker.raf = requestAnimationFrame(tickerFrame);
}

function tickerSync() {
  if (!ticker.track) return;
  if (reducedMotion.matches || document.hidden) {
    if (ticker.raf) cancelAnimationFrame(ticker.raf);
    ticker.raf = 0; ticker.last = 0;
    if (reducedMotion.matches) { ticker.track.style.transform = ""; ticker.offset = 0; }
    return;
  }
  if (!ticker.raf) { ticker.last = 0; ticker.raf = requestAnimationFrame(tickerFrame); }
}

function tickerHold(on, who) { if (on) ticker.held.add(who); else ticker.held.delete(who); }

function renderTicker() {
  const host = document.getElementById("ticker");
  const items = tickerItems(state.summary?.ticker);
  host.textContent = "";
  host.hidden = !items.length;
  if (!items.length) return;
  const firstDown = items.findIndex((i) => i.dir === "down");
  const copy = (dup) => {
    const track = el("div", { class: "tk-copy" });
    items.forEach((i, idx) => {
      if (idx === firstDown && idx > 0) track.append(el("span", { class: "tk-sep" }, "┃"));
      track.append(el("span", { class: `tk-item ${i.dir}` },
        el("b", {}, i.symbol), " ", i.price, " ", el("span", { class: "tk-chg" }, `${i.mark} ${i.change}`)));
    });
    track.append(el("span", { class: "tk-sep" }, "┃"));
    if (dup) track.classList.add("tk-dup");
    return track;
  };
  const track = el("div", { class: "tk-track", "aria-hidden": "true" }, copy(false), copy(true));
  const win = el("div", { class: "tk-window" }, track);
  ticker.track = track; ticker.offset = 0; ticker.speed = 1; ticker.held.clear();
  win.addEventListener("mouseenter", () => tickerHold(true, "hover"));
  win.addEventListener("mouseleave", () => tickerHold(false, "hover"));
  win.addEventListener("focusin", () => tickerHold(true, "focus"));
  win.addEventListener("focusout", () => tickerHold(false, "focus"));
  win.addEventListener("touchstart", () => tickerHold(true, "touch"), { passive: true });
  for (const t of ["touchend", "touchcancel"]) win.addEventListener(t, () => tickerHold(false, "touch"), { passive: true });
  host.append(
    win,
    el("p", { class: "tk-note" }, "Previous-day price moves of the tracked assets. Not advice."),
    el("ul", { class: "sr-only" }, ...items.map((i) => el("li", {}, i.text))),
  );
  tickerSync();
}
document.addEventListener("visibilitychange", tickerSync);
reducedMotion.addEventListener?.("change", tickerSync);

function applyPalette() {
  document.documentElement.dataset.palette = state.palette;
  document.getElementById("palette").setAttribute("aria-pressed", String(state.palette === "cvd"));
}

async function boot() {
  applyPalette();
  try {
    state.summary = await getJSON("data/summary.json");
    loadError = false;
  } catch {
    return showError("Couldn't load the data. Check your connection, then retry.", boot);
  }
  renderTicker();
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
