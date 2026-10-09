from bench.store import SCHEMA_VERSION

NAME = "ensemble"
LABEL = "Ensemble (majority vote)"
META = {
    "label": LABEL, "kind": "derived",
    "source": "majority vote of the non-control estimators",
    "license": "n/a", "original_code": False,
}


def derive(saved_by_model, costs):
    """Majority vote of the voting models, per run date and asset. Controls must not be passed in."""
    run_dates = sorted({rd for saved in saved_by_model.values() for rd in saved})
    out = {}
    for rd in run_dates:
        votes = {}  # asset -> list of (asof, expected_return)
        for model in sorted(saved_by_model):
            payload = saved_by_model[model].get(rd)
            if not payload:
                continue
            for asset, p in payload["predictions"].items():
                votes.setdefault(asset, []).append((p["asof"], float(p["expected_return"])))
        preds = {}
        for asset in sorted(votes):
            newest = max(a for a, _e in votes[asset])
            exps = [e for a, e in votes[asset] if a == newest]
            rt = costs.round_trip(asset)
            up = sum(1 for e in exps if e > rt)
            down = sum(1 for e in exps if e < -rt)
            value = 1.0 if up > len(exps) / 2 else (-1.0 if down > len(exps) / 2 else 0.0)
            preds[asset] = {"asof": newest, "expected_return": value, "confidence": None, "path": None}
        if preds:
            out[rd] = {
                "schema_version": SCHEMA_VERSION, "estimator": NAME, "run_date": rd,
                "created_at": None, "predictions": preds,
            }
    return out
