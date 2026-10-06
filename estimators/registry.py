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
}


def names():
    return list(REGISTRY)


def build(name):
    module, cls = REGISTRY[name]["target"].split(":")
    return getattr(importlib.import_module(module), cls)()
