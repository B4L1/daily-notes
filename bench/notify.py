import json
import urllib.parse
import urllib.request
from pathlib import Path


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
    if failure:
        title = f"Prediction bench {run_date}"
        body = "The daily run failed. Open the run to see why."
        click = env.get("RUN_URL", "")
    else:
        summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
        title, body = build_message(summary, run_date)
        click = env.get("SITE_URL", "")
    try:
        send(topic, title, body, click, 2, opener)
    except Exception as e:
        # Print only the exception type: its message can contain the URL, which holds the topic.
        print(f"notification failed: {type(e).__name__}")
        return 1
    return 0
