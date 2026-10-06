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

export function luckText(row) {
  if (!row.n_days) return "no data";
  if (row.too_early) return `too early to tell (${row.n_days} day${row.n_days === 1 ? "" : "s"} so far)`;
  return row.p_value < 0.05
    ? `unlikely luck (p=${row.p_value.toFixed(3)})`
    : `consistent with luck (p=${row.p_value.toFixed(2)})`;
}
