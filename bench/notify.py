import json
import re
import urllib.parse
import urllib.request
from pathlib import Path


_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _clean(text):
    """Drop control chars/newlines and make the text safe for an HTTP header (latin-1)."""
    text = "".join(c for c in str(text) if c.isprintable())
    return text.encode("ascii", "replace").decode()


def _safe_click(url):
    url = _clean(url or "").strip()
    return url if url.startswith("https://") else ""


def _pct(v):
    return f"{v * 100:+.2f}%"


def build_message(summary, run_date):
    labels = {e["name"]: e["label"] for e in summary["estimators"]}
    rows = summary["modes"]["live"]["rows"]
    problems = [labels[n] for n, r in rows.items() if r["status"] in ("failed", "skipped_late")]
    active = {n: r for n, r in rows.items() if not n.startswith("control_") and r["n_days"] > 0}
    parts = []
    if not active:
        parts.append(f"Predictions logged for {run_date}. First results appear after the next session closes.")
    else:
        best = max(active, key=lambda n: active[n]["day_return"])
        worst = min(active, key=lambda n: active[n]["day_return"])
        rand = rows.get("control_random", {}).get("day_return")
        beat = sum(1 for r in active.values() if rand is not None and r["day_return"] > rand)
        day_n = max(r["n_days"] for r in rows.values())
        parts.append(
            f"Day {day_n}: best {labels[best]} {_pct(active[best]['day_return'])}, "
            f"worst {labels[worst]} {_pct(active[worst]['day_return'])}."
        )
        parts.append(f"{beat} of {len(active)} beat random.")
    if problems:
        parts.append("Problem: " + ", ".join(problems) + ".")
    return f"Prediction bench {run_date}", " ".join(parts)


def send(topic, title, body, click, priority=2, opener=urllib.request.urlopen):
    headers = {"Title": title, "Priority": str(priority)}
    if click:
        headers["Click"] = click
    req = urllib.request.Request(
        f"https://ntfy.sh/{urllib.parse.quote(topic, safe='')}", data=body.encode("utf-8"), method="POST", headers=headers
    )
    with opener(req, timeout=15) as resp:
        return resp.status


def notify(summary_path, run_date, failure, env, opener=urllib.request.urlopen):
    topic = env.get("NTFY_TOPIC")
    if not topic:
        print("NTFY_TOPIC is not set; skipping the notification.")
        return 0
    run_date = run_date if _DATE.fullmatch(str(run_date)) else "unknown date"
    title = f"Prediction bench {run_date}"
    run_url = env.get("RUN_URL", "")
    if failure:
        body = "The daily run failed. Open the run to see why."
        click = run_url
    else:
        try:
            summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
            title, body = build_message(summary, run_date)
            click = env.get("SITE_URL", "")
        except Exception as e:
            print(f"summary unreadable: {type(e).__name__}")
            body = "The run finished but the summary is missing or unreadable. Open the run to see why."
            click = run_url
    try:
        # A non-2xx status is not treated as failure here; urlopen raises for most of them.
        send(topic, _clean(title), _clean(body), _safe_click(click), 2, opener)
    except Exception as e:
        # Print only the exception type: its message can contain the URL, which holds the topic.
        print(f"notification failed: {type(e).__name__}")
        return 1
    return 0
