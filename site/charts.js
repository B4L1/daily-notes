const NS = "http://www.w3.org/2000/svg";
const svg = (tag, attrs = {}) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) n.setAttribute(k, v);
  return n;
};
const day = (s) => Date.parse(s + "T00:00:00Z") / 86400000;

export function sparkline(values, { width = 120, height = 28 } = {}) {
  if (!values || values.length < 2) return document.createElement("span");
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values
    .map((v, i) => `${((i / (values.length - 1)) * width).toFixed(1)},${(height - 2 - ((v - min) / span) * (height - 4)).toFixed(1)}`)
    .join(" ");
  const s = svg("svg", { viewBox: `0 0 ${width} ${height}`, width, height, "aria-hidden": "true" });
  s.append(svg("polyline", { points: pts, fill: "none", stroke: "currentColor", "stroke-width": "1.5" }));
  return s;
}

function note(text) {
  const p = document.createElement("p");
  p.className = "note";
  p.textContent = text;
  return p;
}

export function lineChart(container, series, { height = 240, label = "Account value over time" } = {}) {
  container.textContent = "";
  const usable = series.filter((s) => s.points.length > 0);
  const all = usable.flatMap((s) => s.points);
  const xs = all.map((p) => day(p[0]));
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  if (all.length < 2 || x1 === x0) {
    container.append(note("Not enough days to draw a chart yet."));
    return;
  }
  const W = 800, padL = 56, padR = 8, padT = 8, padB = 20;
  const ys = all.map((p) => p[1]);
  let y0 = Math.min(...ys);
  let y1 = Math.max(...ys);
  if (y1 === y0) { y0 -= 1; y1 += 1; }
  const sx = (d) => padL + ((day(d) - x0) / (x1 - x0)) * (W - padL - padR);
  const sy = (v) => padT + (1 - (v - y0) / (y1 - y0)) * (height - padT - padB);
  const s = svg("svg", { viewBox: `0 0 ${W} ${height}`, class: "chart", role: "img", "aria-label": label, width: "100%" });
  for (const v of [y0, (y0 + y1) / 2, y1]) {
    s.append(svg("line", { x1: padL, x2: W - padR, y1: sy(v), y2: sy(v), stroke: "#30363d", "stroke-width": "1" }));
    const t = svg("text", { x: padL - 6, y: sy(v) + 3, "text-anchor": "end" });
    t.textContent = "$" + Math.round(v).toLocaleString("en-US");
    s.append(t);
  }
  const dates = all.map((p) => p[0]).sort();
  const left = svg("text", { x: padL, y: height - 4 });
  left.textContent = dates[0];
  const right = svg("text", { x: W - padR, y: height - 4, "text-anchor": "end" });
  right.textContent = dates[dates.length - 1];
  s.append(left, right);
  for (const ser of usable) {
    const pts = ser.points.map((p) => `${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join(" ");
    s.append(svg("polyline", {
      points: pts, fill: "none", stroke: ser.color,
      "stroke-width": ser.dashed ? "1" : "1.6", "stroke-dasharray": ser.dashed ? "4 3" : undefined,
    }));
  }
  container.append(s);
  const legend = document.createElement("div");
  legend.className = "legend";
  for (const ser of usable) {
    const item = document.createElement("span");
    const sw = document.createElement("i");
    sw.style.background = ser.color;
    item.append(sw, ser.name);
    legend.append(item);
  }
  container.append(legend);
}
