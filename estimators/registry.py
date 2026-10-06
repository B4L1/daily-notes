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
}


def names():
    return list(REGISTRY)


def build(name):
    module, cls = REGISTRY[name]["target"].split(":")
    return getattr(importlib.import_module(module), cls)()
