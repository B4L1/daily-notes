import test from "node:test";
import assert from "node:assert/strict";
import { cellColor, signMark, fmtPct, fmtUsd, calendarCells, luckText } from "./lib.js";

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
  assert.equal(luckText({ n_days: 10, too_early: true, p_value: 0.001 }), "too early to tell");
  assert.match(luckText({ n_days: 90, too_early: false, p_value: 0.01 }), /^unlikely luck/);
  assert.match(luckText({ n_days: 90, too_early: false, p_value: 0.4 }), /^consistent with luck/);
});
