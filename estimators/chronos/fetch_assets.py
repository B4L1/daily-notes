"""One-off preparation for the Chronos estimator, run before predict (never from predict).

The code is the pinned PyPI package (estimators/chronos/requirements.txt). The weights are the
official Amazon Chronos-Bolt (Tiny) checkpoint (Apache-2.0), downloaded at a pinned Hugging Face
revision into data/cache (which CI caches) and verified by sha256 here and before every load.
"""
import hashlib
import os
from pathlib import Path

REPO = "amazon/chronos-bolt-tiny"
REVISION = "a0e552de83495b5c28c14c71c374f3e33280b340"
WEIGHTS_SHA256 = "75068728d376d2bec670379eeef4bfb4d24c0cfe24d957451f8d19b447030a32"  # model.safetensors


def weights_dir():
    return Path(os.environ.get("CHRONOS_WEIGHTS", "data/cache/chronos_weights"))


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def weights_ok():
    f = weights_dir() / "model.safetensors"
    return f.is_file() and _sha(f) == WEIGHTS_SHA256


def main():
    if weights_ok():
        return
    from huggingface_hub import snapshot_download

    # plain files in the cache dir (no symlinks, which Windows forbids without privileges)
    print(snapshot_download(REPO, revision=REVISION, local_dir=weights_dir(),
                            allow_patterns=["config.json", "model.safetensors"]))
    if not weights_ok():
        raise RuntimeError(f"{REPO}: model.safetensors sha256 mismatch, refusing to use it")


if __name__ == "__main__":
    main()
