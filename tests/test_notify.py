import json

from bench.notify import build_message, notify, send


def summary(rows):
    names = ["control_random", "analog", "xgb_indicators"]
    return {
        "estimators": [{"name": n, "label": n.upper(), "kind": "control" if n.startswith("control") else "ml"} for n in names],
        "modes": {"live": {"rows": {n: rows.get(n, {"status": "ok", "n_days": 0, "day_return": None}) for n in names}}},
    }


def row(day_return, n_days=5, status="ok"):
    return {"status": status, "n_days": n_days, "day_return": day_return}


def test_first_day_message_has_no_results_yet():
    title, body = build_message(summary({}), "2026-01-06")
    assert "2026-01-06" in title and "First results appear" in body


def test_message_names_best_worst_and_beats_random():
    s = summary({"control_random": row(0.001), "analog": row(0.0215), "xgb_indicators": row(-0.0034)})
    _, body = build_message(s, "2026-01-06")
    assert "best ANALOG +2.15%" in body and "worst XGB_INDICATORS -0.34%" in body
    assert "1 of 2 beat random" in body and body.startswith("Day 5")


def test_failures_are_reported():
    s = summary({"control_random": row(0.0), "analog": row(0.01), "xgb_indicators": row(0.01, status="failed")})
    _, body = build_message(s, "2026-01-06")
    assert "Problem: XGB_INDICATORS" in body


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_send_builds_the_request():
    seen = {}

    def opener(req, timeout):
        seen.update(url=req.full_url, headers=dict(req.header_items()), data=req.data, method=req.get_method())
        return FakeResponse()

    assert send("secret-topic", "Title", "Body é", "https://x.example/", 2, opener) == 200
    assert seen["url"] == "https://ntfy.sh/secret-topic" and seen["method"] == "POST"
    assert seen["headers"]["Priority"] == "2" and seen["headers"]["Click"] == "https://x.example/"
    assert seen["data"] == "Body é".encode("utf-8")


def test_notify_skips_quietly_without_a_topic(tmp_path, capsys):
    assert notify(tmp_path / "none.json", "2026-01-06", False, {}) == 0
    assert "skipping" in capsys.readouterr().out


def test_notify_failure_message_and_no_topic_leak(tmp_path, capsys):
    calls = []

    def opener(req, timeout):
        calls.append(req)
        raise OSError("boom https://ntfy.sh/secret-topic")

    code = notify(tmp_path / "none.json", "2026-01-06", True, {"NTFY_TOPIC": "secret-topic", "RUN_URL": "https://r"}, opener)
    out = capsys.readouterr()
    assert code == 1 and calls
    assert "secret-topic" not in out.out + out.err


def test_notify_success_reads_the_summary(tmp_path):
    p = tmp_path / "summary.json"
    p.write_text(json.dumps(summary({})))
    sent = []

    def opener(req, timeout):
        sent.append(req.data.decode())
        return FakeResponse()

    assert notify(p, "2026-01-06", False, {"NTFY_TOPIC": "t", "SITE_URL": "https://s/"}, opener) == 0
    assert "First results appear" in sent[0]
