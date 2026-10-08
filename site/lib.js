export const PALETTES = {
  default: { pos: [63, 185, 80], neg: [248, 81, 73] },
  cvd: { pos: [88, 166, 255], neg: [240, 136, 62] },
};

export function cellColor(value, scale, palette = "default") {
  if (value === null || value === undefined || Number.isNaN(value)) return "var(--cell-empty)";
  if (value === 0) return "var(--cell-flat)";
  const [r, g, b] = value >= 0 ? PALETTES[palette].pos : PALETTES[palette].neg;
  const alpha = 0.2 + 0.8 * Math.min(Math.abs(value) / scale, 1);
  return `rgba(${r},${g},${b},${alpha.toFixed(2)})`;
}

// Hit rate 0..1 -> deviation from a coin flip, so 50% is neutral.
export function hitDeviation(v) {
  return v === null || v === undefined || Number.isNaN(v) ? null : v - 0.5;
}

export function signMark(v) {
  return v > 0 ? "▲" : v < 0 ? "▼" : "•";
}

export function fmtPct(v, digits = 2) {
  if (v === null || v === undefined) return "n/a";
  return (v > 0 ? "+" : "") + (v * 100).toFixed(digits) + "%";
}

export function fmtUsd(v) {
  if (v === null || v === undefined) return "n/a";
  return "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

const toDay = (s) => Math.floor(Date.parse(s + "T00:00:00Z") / 86400000);

export function calendarCells(dates) {
  if (!dates.length) return [];
  const first = toDay(dates[0]);
  const last = toDay(dates[dates.length - 1]);
  const offset = new Date(first * 86400000).getUTCDay(); // 0 = Sunday
  const cells = [];
  for (let d = first; d <= last; d++) {
    const idx = d - first + offset;
    cells.push({
      date: new Date(d * 86400000).toISOString().slice(0, 10),
      col: Math.floor(idx / 7),
      row: idx % 7,
    });
  }
  return cells;
}

export const HOLD_LABEL = "Equal-weight daily rebalanced hold (assets with a session that day, no costs)";
export const STALE_HOURS = 36;
const ALPHA = 0.05;

// Number of estimators that get a luck check: everything that is not a control.
export function testedCount(estimators) {
  return (estimators ?? []).filter((e) => e && e.kind !== "control").length;
}

// Bonferroni: with N estimators tested, one p < 0.05 is expected by chance, so use 0.05 / N.
export function luckThreshold(nTests) {
  const n = Number.isFinite(nTests) && nTests >= 1 ? Math.floor(nTests) : 1;
  return ALPHA / n;
}

function thresholdText(n) {
  const t = luckThreshold(n);
  return n > 1 ? `0.05/${Math.floor(n)} = ${t.toFixed(4)}` : "0.05";
}

export function luckText(row, nTests = 1) {
  if (!row.n_days) return "no data";
  if (row.too_early) return `too early to tell (${row.n_days} day${row.n_days === 1 ? "" : "s"} so far)`;
  const limit = thresholdText(nTests);
  return row.p_value < luckThreshold(nTests)
    ? `unlikely luck (p=${row.p_value.toFixed(3)}, below ${limit})`
    : `consistent with luck (p=${row.p_value.toFixed(2)}, not below ${limit})`;
}

// Data freshness. generated_at is an ISO UTC string; null-safe: unknown age counts as stale.
export function staleness(generatedAt, now = new Date(), limitHours = STALE_HOURS) {
  const t = typeof generatedAt === "string" ? Date.parse(generatedAt) : NaN;
  const n = now instanceof Date ? now.getTime() : Date.parse(now);
  if (!Number.isFinite(t) || !Number.isFinite(n)) return { stale: true, ageHours: null };
  const ageHours = (n - t) / 3600000;
  return { stale: ageHours > limitHours, ageHours };
}

export function freshnessText(summary) {
  const run = summary?.run_date ?? "unknown";
  const gen = summary?.generated_at ?? "unknown";
  return `Data as of ${run}, generated ${String(gen).replace("T", " ").replace(/Z$/, "")} UTC`;
}

// One short line for the top of the page: when the data was produced and what each mode covers.
export function updatedLine(summary) {
  const gen = summary?.generated_at;
  const when = typeof gen === "string" && Number.isFinite(Date.parse(gen))
    ? gen.replace("T", " ").replace(/Z$/, "").slice(0, 16) + " UTC" : "unknown";
  const liveDays = summary?.modes?.live?.dates?.length ?? 0;
  const btDates = summary?.modes?.backtest?.dates ?? [];
  const btEnd = btDates.length ? btDates[btDates.length - 1] : null;
  const live = liveDays ? `Live: ${liveDays} settled day${liveDays === 1 ? "" : "s"}` : "Live: no settled days yet";
  const bt = btEnd ? `Backtest: fixed replay ending ${btEnd}, does not update` : "Backtest: none";
  return `Updated ${when} · ${live} · ${bt}`;
}

export function validPalette(p) {
  return typeof p === "string" && Object.prototype.hasOwnProperty.call(PALETTES, p) ? p : "default";
}

// Backtest only: an estimator evaluated every Nth day sits in cash on the other days.
export function strideNote(meta) {
  const n = Number(meta?.backfill_stride);
  if (!Number.isFinite(n) || n <= 1) return null;
  const ord = n === 2 ? "2nd" : n === 3 ? "3rd" : n + "th";
  return `evaluated every ${ord} day: balance not comparable`;
}

export function dayHit(d) {
  const hits = (d?.trades ?? []).map((t) => t.hit).filter((h) => h !== null && h !== undefined);
  return hits.length ? hits.reduce((a, b) => a + b, 0) / hits.length : null;
}

// Ticker strip: previous-day move per asset. Sorted by change, biggest gain first; unusable rows are dropped.
export function tickerItems(ticker) {
  if (!Array.isArray(ticker)) return [];
  const rows = [];
  for (const t of ticker) {
    if (!t || typeof t.symbol !== "string" || !t.symbol) continue;
    const close = Number(t.close), chg = Number(t.change_pct);
    if (t.close === null || t.change_pct === null || t.close === undefined || t.change_pct === undefined) continue;
    if (!Number.isFinite(close) || !Number.isFinite(chg) || close <= 0) continue;
    const rounded = Number(chg.toFixed(2));
    const dir = rounded > 0 ? "up" : rounded < 0 ? "down" : "flat";
    const sign = dir === "up" ? "+" : dir === "down" ? "-" : "";
    const price = close.toLocaleString("en-US", { minimumFractionDigits: close < 1 ? 4 : 2, maximumFractionDigits: close < 1 ? 4 : 2 });
    const mark = signMark(rounded);
    const change = `${sign}${Math.abs(rounded).toFixed(2)}%`;
    rows.push({ chg, symbol: t.symbol.toUpperCase(), price, mark, change, dir,
      text: `${t.symbol.toUpperCase()} ${price} ${mark} ${change}` });
  }
  rows.sort((a, b) => b.chg - a.chg);
  return rows.map(({ chg, ...rest }) => rest);
}

// One smoothing step for the ticker speed factor (0 = stopped, 1 = full speed). Exponential, so it never overshoots.
export function easeSpeed(current, target, dtSeconds, tau = 0.25) {
  const clamp = (v) => (Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : 0);
  const cur = clamp(current), tgt = clamp(target);
  if (!(dtSeconds > 0)) return cur;
  if (!(tau > 0)) return tgt;
  return cur + (tgt - cur) * (1 - Math.exp(-dtSeconds / tau));
}
