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
    assert "!cancelled()" in jobs["aggregate"]["if"]
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
    for job in ("fetch", "aggregate", "deploy"):
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


def _steps(doc):
    for jname, job in doc["jobs"].items():
        for step in job["steps"]:
            yield jname, step


def test_only_schedule_and_manual_triggers():
    for name in ("daily.yml", "backfill.yml"):
        _, doc = load(name)
        assert set(triggers(doc)) <= {"schedule", "workflow_dispatch"}
        assert "workflow_dispatch" in triggers(doc)


def test_every_job_has_a_timeout():
    for name in ("daily.yml", "backfill.yml"):
        _, doc = load(name)
        for job_name, job in doc["jobs"].items():
            assert "timeout-minutes" in job, (name, job_name)


def test_matrix_comes_from_fetch_output_and_requirements_are_installed():
    for name, job in (("daily.yml", "predict"), ("backfill.yml", "backtest")):
        text, doc = load(name)
        j = doc["jobs"][job]
        assert "fromJson(needs.fetch.outputs.estimators)" in j["strategy"]["matrix"]["estimator"]
        install = [s for s in j["steps"] if s.get("name") == "Install dependencies"][0]
        assert "bench.cli requirements" in install["run"]


def test_empty_estimator_list_fails_loudly():
    _, doc = load("daily.yml")
    step = [s for s in doc["jobs"]["fetch"]["steps"] if s.get("id") == "list"][0]
    assert "exit 1" in step["run"]


def test_aggregate_does_not_depend_on_predict_result():
    _, doc = load("daily.yml")
    cond = doc["jobs"]["aggregate"]["if"]
    assert "needs.predict" not in cond
    assert "!cancelled()" in cond and "needs.fetch.result == 'success'" in cond
    assert "!cancelled()" in doc["jobs"]["deploy"]["if"]
    _, bf = load("backfill.yml")
    assert "needs.backtest" not in bf["jobs"]["commit"]["if"]


def test_writing_jobs_check_out_full_history():
    for name, job in (("daily.yml", "aggregate"), ("backfill.yml", "commit")):
        _, doc = load(name)
        assert doc["jobs"][job]["steps"][0]["with"]["fetch-depth"] == 0
        run = [s["run"] for s in doc["jobs"][job]["steps"] if s.get("name") == "Commit data"][0]
        assert "for attempt in 1 2 3" in run


def test_backfill_commits_only_backtest_data():
    text, _ = load("backfill.yml")
    assert "git add data/backtest\n" in text
    assert "git add data\n" not in text
    # uncommitted price refreshes must be discarded before pull --rebase, or the rebase refuses to run
    assert text.index("git checkout -- .") < text.index("git pull --rebase")


def test_uploads_overwrite():
    for name in ("daily.yml", "backfill.yml"):
        _, doc = load(name)
        for jname, step in _steps(doc):
            if step.get("uses", "").startswith("actions/upload-artifact"):
                assert step["with"]["overwrite"] is True, (name, jname)


def test_notify_success_vs_failure_conditions():
    _, doc = load("daily.yml")
    steps = {s["name"]: s for s in doc["jobs"]["notify"]["steps"] if s.get("name", "").startswith("Notify")}
    ok, bad = steps["Notify (success)"], steps["Notify (failure)"]
    assert "--failure" not in ok["run"] and "--failure" in bad["run"]
    for job in ("fetch", "aggregate", "deploy"):
        assert f"needs.{job}.result == 'success'" in ok["if"]
        assert f"needs.{job}.result != 'success'" in bad["if"]
    assert "needs.predict" not in ok["if"] and "needs.predict" not in bad["if"]


def test_topic_only_in_notify_step_env():
    for name in ("daily.yml", "backfill.yml"):
        _, doc = load(name)
        for jname, job in doc["jobs"].items():
            assert "NTFY_TOPIC" not in job.get("env", {}), (name, jname)
            for step in job["steps"]:
                if "NTFY_TOPIC" in step.get("env", {}):
                    assert jname == "notify" and step["name"].startswith("Notify")


def test_predict_jobs_prepare_assets_online_then_run_offline():
    # Pretrained models need weights and pinned sources prepared (network) before predict (offline).
    for name, job, step_name in (("daily.yml", "predict", "Predict"), ("backfill.yml", "backtest", "Backfill")):
        _, doc = load(name)
        steps = doc["jobs"][job]["steps"]
        install = next(s for s in steps if s.get("name") == "Install dependencies")
        assert "bench.cli setup" in install["run"]
        assert "HF_HUB_OFFLINE" not in install.get("env", {})
        run = next(s for s in steps if s.get("name") == step_name)
        assert str(run["env"]["HF_HUB_OFFLINE"]) == "1"
        cache = next(s for s in steps if str(s.get("uses", "")).startswith("actions/cache"))
        assert "fetch_assets.py" in cache["with"]["key"]
