#!/usr/bin/env python3
"""Homelab HTTP entry for the blender finish door on a LOCAL_FINISH_* URL (fc#1592).

Blender is CPU-ONLY here: the grade and composite paths run software blender -b plus
ffmpeg, and both proof arms completed with nvidia-smi absent, so this door needs no GPU
reservation and no CUDA-capable node. That is why it targets the finishing tier rather
than the GPU twins.

There is no warm model residency to win here, unlike the model doors: blender is a
subprocess per job and holds nothing between jobs. Running it resident stops paying
RunPod cold start and image pull per job; it does not save a model load.
"""
import os

from handler import handler
from runpod_http_serve import run_serve


def hydrate_secret_files() -> list[str]:
    """Populate NAME from NAME_FILE, the standard Docker/swarm secrets convention.

    Swarm delivers secrets as FILES under /run/secrets, while handler.py reads plain
    environment variables (R2_ACCESS_KEY_ID and friends). Without this bridge a stack file
    would have to carry the values in an environment block, which is exactly the plaintext
    in a tracked file that is not allowed. Doing it here rather than in handler.py keeps
    the handler identical to the one the serverless worker runs.

    An already-set NAME always WINS. The compose doors on the GPU twins pass plain env
    vars from an env_file, and a stale or empty secret file must never silently override
    a value that is already correct.

    Returns the NAMES it filled, never the values.
    """
    filled = []
    for key in sorted(os.environ):
        if not key.endswith("_FILE"):
            continue
        path = os.environ.get(key) or ""
        name = key[:-5]
        if not path or not name or os.environ.get(name):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                value = fh.read().strip()
        except OSError:
            continue
        if not value:
            continue
        os.environ[name] = value
        filled.append(name)
    return filled


if __name__ == "__main__":
    names = hydrate_secret_files()
    # NAMES only. A value reaching stdout would put it in the container log.
    print("hydrated from _FILE: " + (", ".join(names) if names else "none"), flush=True)
    run_serve(
        handler,
        service="vivijure-blender-finish-blender",
        port=int(os.environ.get("PORT", "8014") or "8014"),
    )
