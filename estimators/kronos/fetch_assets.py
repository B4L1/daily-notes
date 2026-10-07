"""One-off preparation for the Kronos estimator, run before predict (never from predict).

Kronos is a repository, not a pip package, and its model weights live on Hugging Face. This
script downloads the pinned commit's three model/*.py files (verified by sha256, kept outside
the repo in the cache directory) and the pinned weight snapshots next to it (both under data/cache, which CI caches).
"""
import hashlib
import os
import urllib.request
from pathlib import Path

KRONOS_COMMIT = "67b630e67f6a18c9e9be918d9b4337c960db1e9a"
SOURCE_SHA256 = {
    "__init__.py": "f8f856ca3fedadcaac97e196be23d1aeda1c3c9ffe8903d66d43ea3bcac6240c",
    "kronos.py": "0a5f90282e2039c2de0771473419715c845def154896dbd0f5747837e6241032",
    "module.py": "a07edbadc0e96804c8158c021bbc6063bb7cc43b34d7fc470d5c8ff2005a409f",
}
WEIGHTS_SHA256 = {  # sha256 of each pinned revision's model.safetensors
    "NeoQuasar/Kronos-small": "b082dfcbd8e8c142a725c8bbb99781802f38fec81210e13479effb32b3c3e020",
    "NeoQuasar/Kronos-Tokenizer-base": "59d85f6af76a2c3b8240ea06cb21db4213b4eeca053f246b23e29cf832fc6bee",
}
WEIGHTS = {  # Hugging Face repo -> pinned revision
    "NeoQuasar/Kronos-small": "901c26c1332695a2a8f243eb2f37243a37bea320",
    "NeoQuasar/Kronos-Tokenizer-base": "0e0117387f39004a9016484a186a908917e22426",
}


def source_dir():
    return Path(os.environ.get("KRONOS_SRC", "data/cache/kronos_src"))


def weights_dir(repo):
    return Path(os.environ.get("KRONOS_WEIGHTS", "data/cache/kronos_weights")) / repo.split("/")[1]


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def source_ok():
    pkg = source_dir() / "model"
    return all((pkg / n).is_file() and _sha(pkg / n) == d for n, d in SOURCE_SHA256.items())


def weights_ok(repo):
    f = weights_dir(repo) / "model.safetensors"
    return f.is_file() and _sha(f) == WEIGHTS_SHA256[repo]


def main():
    pkg = source_dir() / "model"
    pkg.mkdir(parents=True, exist_ok=True)
    for name, digest in SOURCE_SHA256.items():
        target = pkg / name
        if target.is_file() and _sha(target) == digest:
            continue
        url = f"https://raw.githubusercontent.com/shiyu-coder/Kronos/{KRONOS_COMMIT}/model/{name}"
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()
        if hashlib.sha256(data).hexdigest() != digest:
            raise RuntimeError(f"{url}: sha256 mismatch, refusing to use it")
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)  # atomic: a reader never sees a half-written file
    from huggingface_hub import snapshot_download

    for repo, rev in WEIGHTS.items():
        if weights_ok(repo):
            continue
        # plain files in the cache dir (no symlinks, which Windows forbids without privileges)
        print(snapshot_download(repo, revision=rev, local_dir=weights_dir(repo)))
        if not weights_ok(repo):
            raise RuntimeError(f"{repo}: model.safetensors sha256 mismatch, refusing to use it")


if __name__ == "__main__":
    main()
