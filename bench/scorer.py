import math

from bench import ensemble
from bench.costs import Costs
from bench.strategies import STRATEGIES
from bench.strategies.common import Result, index_predictions

CHECKED = ("net_ret", "entry", "exit", "expected_return", "cost", "actual_cc")


def models(registry):
    """Every model that has accounts: the registry's estimators plus the derived ensemble."""
    return list(registry) + [ensemble.NAME]


def _check(model, strategy, result):
    for r in result.ledger:
        for k in CHECKED:
            v = r[k]
            if v is not None and not math.isfinite(v):
                raise ValueError(f"non-finite {k} in {model}/{strategy} on {r['date']} {r['asset']}")
    for e in result.equity:
        if not (math.isfinite(e["equity"]) and math.isfinite(e["day_return"])):
            raise ValueError(f"non-finite equity in {model}/{strategy} on {e['date']}")


def score_store(store, prices, assets, settings, registry):
    """Recompute every account in one store from its predictions. Returns settled days per account.

    Everything is computed and rendered before anything is written, so a failure leaves the store untouched.
    """
    costs = Costs(assets)
    saved = {m: store.load_predictions(m) for m in registry}
    voters = {m: s for m, s in saved.items() if registry[m].get("kind") != "control"}
    derived = ensemble.derive(voters, costs)
    saved[ensemble.NAME] = derived
    results = {}
    for model in models(registry):
        preds = index_predictions(saved[model])
        for strategy, fn in STRATEGIES.items():
            try:
                result = fn(preds, prices, costs, settings.start_equity) if preds else None
            except ZeroDivisionError as e:
                raise ValueError(f"non-finite price (zero open or close) in {model}/{strategy}: {e}") from e
            if result is None:
                result = Result([], [], [])
            _check(model, strategy, result)
            results[(model, strategy)] = (result, store.render_account(result))
    store.replace_predictions(ensemble.NAME, derived)
    done = {}
    for (model, strategy), (result, texts) in results.items():
        store.write_account(model, strategy, texts)
        if result.ledger:
            done[(model, strategy)] = len(result.equity)
    return done
