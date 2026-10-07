import importlib

REGISTRY = {
    "control_always_long": {
        "target": "estimators.controls.predict:AlwaysLong",
        "label": "Always long (control)", "kind": "control",
        "source": "Baseline: buys every asset every day and pays the same costs",
        "license": "own code", "original_code": False,
    },
    "control_random": {
        "target": "estimators.controls.predict:RandomCoin",
        "label": "Random coin (control)", "kind": "control",
        "source": "Baseline: a deterministic coin flip per asset per day",
        "license": "own code", "original_code": False,
    },
    "control_persistence": {
        "target": "estimators.controls.predict:Persistence",
        "label": "Tomorrow = today (control)", "kind": "control",
        "source": "Baseline: predicts that the next return equals the last return",
        "license": "own code", "original_code": False,
    },
    "analog": {
        "target": "estimators.analog.predict:Analog",
        "label": "Analog candle matching", "kind": "pattern",
        "source": "Idea from CandleEdge-style historical pattern matching; our own reimplementation",
        "license": "own code", "original_code": False,
    },
    "candle_rules": {
        "target": "estimators.candle_rules.predict:CandleRules",
        "label": "Candlestick pattern rules", "kind": "pattern",
        "source": "Textbook rules: hammer, shooting star, engulfing; our own implementation",
        "license": "own code", "original_code": False,
    },
    "xgb_indicators": {
        "target": "estimators.xgb_indicators.predict:XgbIndicators",
        "label": "XGBoost on indicators", "kind": "ml",
        "source": "XGBoost regression on RSI, moving averages and recent returns; our own implementation",
        "license": "own code (uses xgboost, Apache-2.0)", "original_code": False,
        "requirements": "estimators/xgb_indicators/requirements.txt",
    },
    "statsforecast_auto": {
        "target": "estimators.statsforecast_auto.predict:StatsforecastAuto",
        "label": "AutoETS (statsforecast)", "kind": "ml",
        "source": "Nixtla statsforecast AutoETS on the last 256 closes, 5-day path; depends on the pinned package",
        "license": "Apache-2.0 (statsforecast)", "original_code": True,
        "requirements": "estimators/statsforecast_auto/requirements.txt",
    },
    "kronos": {
        "target": "estimators.kronos.predict:Kronos",
        "label": "Kronos-small (pretrained)", "kind": "pretrained",
        "source": "Kronos candlestick foundation model (shiyu-coder/Kronos, pinned commit) with NeoQuasar/Kronos-small weights, greedy 5-day path",
        "license": "MIT (code) and MIT (weights)", "original_code": True,
        "requirements": "estimators/kronos/requirements.txt",
        "setup": "estimators.kronos.fetch_assets",
        "backfill_stride": 1,
    },
    "timesfm": {
        "target": "estimators.timesfm.predict:TimesFM",
        "label": "TimesFM 2.5 (pretrained)", "kind": "pretrained",
        "source": "Google Research TimesFM 2.5 200M (timesfm on PyPI, pinned) with google/timesfm-2.5-200m-pytorch weights, point forecast, 5-day path",
        "license": "Apache-2.0 (code) and Apache-2.0 (2.5 weights)", "original_code": True,
        "requirements": "estimators/timesfm/requirements.txt",
        "setup": "estimators.timesfm.fetch_assets",
        "backfill_stride": 1,
    },
    "chronos": {
        "target": "estimators.chronos.predict:Chronos",
        "label": "Chronos-Bolt Tiny (pretrained)", "kind": "pretrained",
        "source": "Amazon Chronos-Bolt (chronos-forecasting on PyPI, pinned) with amazon/chronos-bolt-tiny weights, median forecast, 5-day path",
        "license": "Apache-2.0 (code) and Apache-2.0 (weights)", "original_code": True,
        "requirements": "estimators/chronos/requirements.txt",
        "setup": "estimators.chronos.fetch_assets",
    },
    "lstm": {
        "target": "estimators.lstm.predict:Lstm",
        "label": "LSTM on candle shape", "kind": "ml",
        "source": "Small PyTorch LSTM on 20-day windows of return, range and body; our own implementation, retrained weekly from history up to that week's Monday",
        "license": "own code (uses PyTorch, BSD-3-Clause)", "original_code": False,
        "requirements": "estimators/lstm/requirements.txt",
    },
}


def backfill_stride(name):
    """Backfill evaluates the estimator on every Nth day (default 1). Registry is the single source."""
    return max(1, int(REGISTRY[name].get("backfill_stride", 1)))


def names():
    return list(REGISTRY)


def build(name):
    module, cls = REGISTRY[name]["target"].split(":")
    return getattr(importlib.import_module(module), cls)()
