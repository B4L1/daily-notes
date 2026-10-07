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
WEIGHTS = {  # Hugging Face repo -> pinned revision
    "NeoQuasar/Kronos-small": "901c26c1332695a2a8f243eb2f37243a37bea320",
    "NeoQuasar/Kronos-Tokenizer-base": "0e0117387f39004a9016484a186a908917e22426",
}


def source_dir():
    return Path(os.environ.get("KRONOS_SRC", "data/cache/kronos_src"))


def weights_dir(repo):
    return Path(os.environ.get("KRONOS_WEIGHTS", "data/cache/kronos_weights")) / repo.split("/")[1]


def main():
    pkg = source_dir() / "model"
    pkg.mkdir(parents=True, exist_ok=True)
    for name, digest in SOURCE_SHA256.items():
        target = pkg / name
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
            continue
        url = f"https://raw.githubusercontent.com/shiyu-coder/Kronos/{KRONOS_COMMIT}/model/{name}"
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()
        if hashlib.sha256(data).hexdigest() != digest:
            raise RuntimeError(f"{url}: sha256 mismatch, refusing to use it")
        target.write_bytes(data)
    from huggingface_hub import snapshot_download

    for repo, rev in WEIGHTS.items():
        # plain files in the cache dir (no symlinks, which Windows forbids without privileges)
        print(snapshot_download(repo, revision=rev, local_dir=weights_dir(repo)))


if __name__ == "__main__":
    main()
