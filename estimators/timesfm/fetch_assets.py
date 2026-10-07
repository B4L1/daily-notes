"""One-off preparation for the TimesFM estimator, run before predict (never from predict).

The code is the pinned PyPI package (estimators/timesfm/requirements.txt). The weights are the
official Google TimesFM 2.5 checkpoint (Apache-2.0), downloaded at a pinned Hugging Face revision
into data/cache (which CI caches) and verified by sha256 here and before every load.
"""
import hashlib
import os
from pathlib import Path

REPO = "google/timesfm-2.5-200m-pytorch"
REVISION = "1d952420fba87f3c6dee4f240de0f1a0fbc790e3"
WEIGHTS_SHA256 = "2f776efe6245e42b24bc4153ffdf61810140210e4bd3b01fb21f7aa779ab6ce8"  # model.safetensors


def weights_dir():
    return Path(os.environ.get("TIMESFM_WEIGHTS", "data/cache/timesfm_weights"))


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
