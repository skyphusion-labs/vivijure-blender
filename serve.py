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

if __name__ == "__main__":
    run_serve(
        handler,
        service="vivijure-blender-finish-blender",
        port=int(os.environ.get("PORT", "8014") or "8014"),
    )
