import test from "node:test";
import assert from "node:assert/strict";
import { cellColor, signMark, fmtPct, fmtUsd, calendarCells, luckText, hitDeviation, dayHit,
  testedCount, luckThreshold, staleness, freshnessText, updatedLine, validPalette, strideNote, tickerItems, easeSpeed, HOLD_LABEL } from "./lib.js";

test("fmtPct keeps the sign and handles missing values", () => {
  assert.equal(fmtPct(0.0123), "+1.23%");
  assert.equal(fmtPct(-0.005), "-0.50%");
  assert.equal(fmtPct(0), "0.00%");
  assert.equal(fmtPct(null), "n/a");
});

test("fmtUsd", () => {
  assert.equal(fmtUsd(10190), "$10,190.00");
  assert.equal(fmtUsd(null), "n/a");
});

test("signMark gives a non-colour signal", () => {
  assert.equal(signMark(0.01), "▲");
  assert.equal(signMark(-0.01), "▼");
  assert.equal(signMark(0), "•");
});

test("cellColor scales alpha with magnitude and clamps", () => {
  assert.equal(cellColor(0.02, 0.02), "rgba(63,185,80,1.00)");
  assert.equal(cellColor(0.5, 0.02), "rgba(63,185,80,1.00)");
  assert.equal(cellColor(-0.01, 0.02), "rgba(248,81,73,0.60)");
  assert.equal(cellColor(0.01, 0.02, "cvd"), "rgba(88,166,255,0.60)");
  assert.equal(cellColor(-0.02, 0.02, "cvd"), "rgba(240,136,62,1.00)");
});

test("cellColor handles empty cells", () => {
  assert.equal(cellColor(null, 0.02), "var(--cell-empty)");
  assert.equal(cellColor(undefined, 0.02), "var(--cell-empty)");
  assert.equal(cellColor(NaN, 0.02), "var(--cell-empty)");
});

test("calendarCells fills the gaps and starts on the right weekday", () => {
  // 2026-01-05 is a Monday, so row 1 (Sunday is row 0).
  const cells = calendarCells(["2026-01-05", "2026-01-07"]);
  assert.deepEqual(cells.map((c) => c.date), ["2026-01-05", "2026-01-06", "2026-01-07"]);
  assert.equal(cells[0].row, 1);
  assert.equal(cells[0].col, 0);
  assert.equal(cells[2].row, 3);
});

test("calendarCells rolls into the next week", () => {
  const cells = calendarCells(["2026-01-09", "2026-01-12"]); // Friday to Monday
  assert.equal(cells[0].col, 0);
  assert.equal(cells.at(-1).col, 1);
  assert.equal(cells.at(-1).row, 1);
});

test("calendarCells with one date and none", () => {
  assert.equal(calendarCells(["2026-01-05"]).length, 1);
  assert.deepEqual(calendarCells([]), []);
});

test("luckText never overclaims", () => {
  assert.equal(luckText({ n_days: 0 }), "no data");
  assert.equal(luckText({ n_days: 10, too_early: true, p_value: 0.001 }), "too early to tell (10 days so far)");
  assert.match(luckText({ n_days: 90, too_early: false, p_value: 0.01 }), /^unlikely luck/);
  assert.match(luckText({ n_days: 90, too_early: false, p_value: 0.4 }), /^consistent with luck/);
});

test("cellColor gives exactly zero a neutral colour", () => {
  assert.equal(cellColor(0, 0.02), "var(--cell-flat)");
  assert.equal(cellColor(NaN, 0.02), "var(--cell-empty)");
});

test("hitDeviation centres hit rate on 50%", () => {
  assert.equal(hitDeviation(0.5), 0);
  assert.equal(hitDeviation(1), 0.5);
  assert.equal(hitDeviation(0), -0.5);
  assert.equal(hitDeviation(null), null);
  assert.equal(hitDeviation(undefined), null);
  assert.equal(hitDeviation(NaN), null);
  assert.equal(cellColor(hitDeviation(0.5), 0.5), "var(--cell-flat)");
});

test("dayHit averages the non-null hits", () => {
  assert.equal(dayHit({ trades: [] }), null);
  assert.equal(dayHit({ trades: [{ hit: null }, {}] }), null);
  assert.equal(dayHit({ trades: [{ hit: 1 }] }), 1);
  assert.equal(dayHit({ trades: [{ hit: 1 }, { hit: 0 }, { hit: null }, { hit: 0 }, { hit: 1 }] }), 0.5);
});

test("calendarCells starting on a Sunday uses row 0", () => {
  const cells = calendarCells(["2026-01-04", "2026-01-05"]);
  assert.deepEqual(cells.map((c) => [c.col, c.row]), [[0, 0], [0, 1]]);
});

test("Bonferroni threshold is 0.05 over the non-control estimators", () => {
  const est = [{ kind: "control" }, { kind: "control" }, { kind: "ml" }, { kind: "pretrained" }, { kind: "pattern" }, { kind: "ml" }];
  assert.equal(testedCount(est), 4);
  assert.equal(testedCount(null), 0);
  assert.equal(luckThreshold(4), 0.0125);
  assert.equal(luckThreshold(0), 0.05);
  assert.equal(luckThreshold(undefined), 0.05);
});

test("luckText applies the corrected threshold and shows it", () => {
  const row = { n_days: 90, too_early: false, p_value: 0.02 };
  assert.match(luckText(row, 1), /^unlikely luck/);
  assert.match(luckText(row, 8), /^consistent with luck \(p=0\.02, not below 0\.05\/8 = 0\.0063\)/);
  assert.match(luckText({ ...row, p_value: 0.004 }, 8), /^unlikely luck \(p=0\.004, below 0\.05\/8 = 0\.0063\)/);
  assert.equal(luckText({ n_days: 10, too_early: true, p_value: 0.001 }, 8), "too early to tell (10 days so far)");
});

test("staleness flags data older than 36 hours and is null-safe", () => {
  const now = new Date("2026-10-08T12:00:00Z");
  assert.deepEqual(staleness("2026-10-08T00:30:00Z", now), { stale: false, ageHours: 11.5 });
  assert.equal(staleness("2026-10-06T23:59:59Z", now).stale, true);
  assert.equal(staleness("2026-10-07T00:00:00Z", now).stale, false); // exactly 36 h
  assert.deepEqual(staleness(null, now), { stale: true, ageHours: null });
  assert.deepEqual(staleness(undefined, now), { stale: true, ageHours: null });
  assert.deepEqual(staleness("garbage", now), { stale: true, ageHours: null });
});

test("freshnessText shows run date and generation time, null-safe", () => {
  assert.equal(freshnessText({ run_date: "2026-10-07", generated_at: "2026-10-07T01:02:03Z" }),
    "Data as of 2026-10-07, generated 2026-10-07 01:02:03 UTC");
  assert.match(freshnessText(null), /unknown/);
});

test("validPalette falls back to default", () => {
  assert.equal(validPalette("cvd"), "cvd");
  assert.equal(validPalette("default"), "default");
  for (const bad of ["neon", "", null, undefined, "__proto__", "toString", 3]) assert.equal(validPalette(bad), "default");
});

test("strideNote warns only when an estimator is evaluated every Nth day", () => {
  assert.equal(strideNote({ backfill_stride: 1 }), null);
  assert.equal(strideNote({}), null);
  assert.equal(strideNote(null), null);
  assert.equal(strideNote({ backfill_stride: 3 }), "evaluated every 3rd day: balance not comparable");
  assert.equal(strideNote({ backfill_stride: 2 }), "evaluated every 2nd day: balance not comparable");
  assert.equal(strideNote({ backfill_stride: 5 }), "evaluated every 5th day: balance not comparable");
});

test("the reference line is named for what it computes", () => {
  assert.match(HOLD_LABEL, /^Buy and hold, fees paid/);
});

test("updatedLine shows update time, live day count and the fixed backtest end, null-safe", () => {
  const s = { generated_at: "2026-10-08T06:24:35Z", modes: { live: { dates: ["2026-10-08"] }, backtest: { dates: ["2025-10-08", "2026-10-06"] } } };
  assert.equal(updatedLine(s), "Updated 2026-10-08 06:24 UTC · Live: 1 settled day · Backtest: fixed replay ending 2026-10-06, does not update");
  assert.match(updatedLine({ generated_at: "2026-10-08T06:24:35Z", modes: { live: { dates: [] }, backtest: { dates: [] } } }), /Live: no settled days yet · Backtest: none/);
  assert.match(updatedLine(null), /^Updated unknown · Live: no settled days yet/);
  assert.match(updatedLine({ generated_at: "garbage" }), /^Updated unknown/);
});

test("tickerItems sorts winners first and formats price, mark and signed change", () => {
  const items = tickerItems([
    { symbol: "tsla", close: 240.5, change_pct: -1.5 },
    { symbol: "NVDA", close: 182.4, change_pct: 2.314 },
    { symbol: "BTC-USD", close: 67123.456, change_pct: 0.001 },
  ]);
  assert.deepEqual(items.map((i) => i.symbol), ["NVDA", "BTC-USD", "TSLA"]);
  assert.equal(items[0].text, "NVDA 182.40 ▲ +2.31%");
  assert.equal(items[0].dir, "up");
  assert.equal(items[2].text, "TSLA 240.50 ▼ -1.50%");
  assert.equal(items[2].dir, "down");
  assert.equal(items[1].price, "67,123.46");
});

test("tickerItems shows no sign for a zero (or rounds-to-zero) move", () => {
  const [a, b] = tickerItems([{ symbol: "A", close: 10, change_pct: 0 }, { symbol: "B", close: 10, change_pct: -0.004 }]);
  assert.equal(a.text, "A 10.00 • 0.00%");
  assert.equal(a.dir, "flat");
  assert.equal(b.change, "0.00%");
  assert.equal(b.dir, "flat");
});

test("tickerItems rounds to two decimals and keeps cheap prices precise", () => {
  const [a] = tickerItems([{ symbol: "X", close: 0.12345, change_pct: 1.005 }]);
  assert.equal(a.price, "0.1235");
  assert.match(a.change, /^\+1\.0[01]%$/);
});

test("tickerItems tolerates missing, null and NaN data", () => {
  assert.deepEqual(tickerItems(undefined), []);
  assert.deepEqual(tickerItems(null), []);
  assert.deepEqual(tickerItems("nope"), []);
  assert.deepEqual(tickerItems([
    null, {}, { symbol: "A" }, { symbol: "B", close: null, change_pct: 1 }, { symbol: "C", close: 5, change_pct: null },
    { symbol: "D", close: NaN, change_pct: 1 }, { symbol: "E", close: 5, change_pct: NaN }, { symbol: "F", close: 0, change_pct: 1 },
    { symbol: "G", close: -3, change_pct: 1 }, { symbol: "H", close: Infinity, change_pct: 1 },
  ]), []);
});

test("easeSpeed converges to the target without overshooting", () => {
  let v = 1;
  const seen = [];
  for (let i = 0; i < 120; i++) { v = easeSpeed(v, 0, 1 / 60, 0.25); seen.push(v); }
  assert.ok(seen.every((x, i) => x >= 0 && (i === 0 || x < seen[i - 1] || x === 0)));
  assert.ok(v < 0.001);
  let u = 0;
  for (let i = 0; i < 300; i++) { u = easeSpeed(u, 1, 1 / 60, 0.25); assert.ok(u <= 1); }
  assert.ok(u > 0.999);
});

test("easeSpeed: dt=0 leaves it unchanged, huge dt lands on target, inputs are clamped", () => {
  assert.equal(easeSpeed(0.4, 1, 0, 0.25), 0.4);
  assert.equal(easeSpeed(0.4, 1, -1, 0.25), 0.4);
  assert.equal(easeSpeed(0.4, 1, 1000, 0.25), 1);
  assert.equal(easeSpeed(5, 5, 0.1), 1);
  assert.equal(easeSpeed(-2, -3, 0.1), 0);
  assert.equal(easeSpeed(NaN, 1, 0), 0);
  assert.equal(easeSpeed(0.5, 0, 0.1, 0), 0);
  // about 0.7 s to be nearly stopped with tau 0.25 (e^-2.8 ~ 6%)
  assert.ok(easeSpeed(1, 0, 0.7, 0.25) < 0.07);
});
