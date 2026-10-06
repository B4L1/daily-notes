from pathlib import Path

import yaml

from estimators.registry import REGISTRY

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / ".github" / "workflows"


def load(name):
    text = (WF / name).read_text(encoding="utf-8")
    return text, yaml.safe_load(text)


def triggers(doc):
    return doc.get("on", doc.get(True))  # PyYAML reads the bare key `on` as True


def test_daily_schedule_and_manual_trigger():
    _, doc = load("daily.yml")
    assert triggers(doc)["schedule"] == [{"cron": "30 0 * * *"}]
    assert "run_date" in triggers(doc)["workflow_dispatch"]["inputs"]


def test_daily_job_graph():
    _, doc = load("daily.yml")
    jobs = doc["jobs"]
    assert jobs["predict"]["strategy"]["fail-fast"] is False
    assert jobs["predict"]["needs"] == "fetch"
    assert set(jobs["aggregate"]["needs"]) == {"fetch", "predict"}
    assert "always()" in jobs["aggregate"]["if"]
    assert jobs["deploy"]["environment"]["name"] == "github-pages"
    assert "notify" in jobs


def test_workflows_never_overlap_on_data():
    for name in ("daily.yml", "backfill.yml"):
        _, doc = load(name)
        assert doc["concurrency"]["group"] == "bench-data"
        assert doc["concurrency"]["cancel-in-progress"] is False


def test_topic_only_ever_comes_from_the_secret():
    for name in ("daily.yml", "backfill.yml"):
        text, _ = load(name)
        for line in text.splitlines():
            if "NTFY_TOPIC" in line:
                assert "secrets.NTFY_TOPIC" in line, line
            assert "echo" not in line or "NTFY" not in line


def test_data_is_verified_before_it_is_committed():
    for name in ("daily.yml", "backfill.yml"):
        text, _ = load(name)
        assert text.index("verify_data.py") < text.index("git commit")


def test_registry_files_exist():
    for name, m in REGISTRY.items():
        module = m["target"].split(":")[0].replace(".", "/") + ".py"
        assert (ROOT / module).exists(), name
        if "requirements" in m:
            assert (ROOT / m["requirements"]).exists(), name


def test_notify_always_runs_and_flags_any_upstream_failure():
    text, doc = load("daily.yml")
    notify = doc["jobs"]["notify"]
    assert "always()" in notify["if"]
    assert set(notify["needs"]) == {"fetch", "predict", "aggregate", "deploy"}
    assert "--failure" in text
    for job in ("fetch", "predict", "aggregate", "deploy"):
        assert f"needs.{job}.result" in text


def test_token_permissions_are_minimal():
    for name in ("daily.yml", "backfill.yml"):
        _, doc = load(name)
        assert doc["permissions"] == {"contents": "read"}
        for job_name, job in doc["jobs"].items():
            perms = job.get("permissions", {})
            assert "write-all" not in str(perms)
            writes = {k for k, v in perms.items() if v == "write"}
            if job_name in ("aggregate", "commit"):
                assert writes == {"contents"}
            elif job_name == "deploy":
                assert writes == {"pages", "id-token"}
            else:
                assert not writes, (name, job_name)


def test_no_expression_is_spliced_into_scripts():
    # Contexts must reach shell scripts through env, never inside `run:` text.
    for name in ("daily.yml", "backfill.yml"):
        _, doc = load(name)
        for job in doc["jobs"].values():
            for step in job["steps"]:
                assert "${{" not in step.get("run", ""), (name, step["run"])
