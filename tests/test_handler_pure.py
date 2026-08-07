"""CPU-only tests for vivijure-blender pure helpers (no Blender, no GPU)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("handler", ROOT / "handler.py")
assert spec and spec.loader
# Avoid runpod.serverless.start side effects: load module after stubbing runpod if needed.
sys.path.insert(0, str(ROOT))
handler = importlib.util.module_from_spec(spec)
# Pre-register so relative imports work
sys.modules["handler"] = handler
spec.loader.exec_module(handler)


def test_default_output_key():
    assert handler._default_output_key("renders/p/clips/shot.mp4") == "renders/p/clips/shot_bl.mp4"
    assert handler._default_output_key("renders/p/clips/shot") == "renders/p/clips/shot_bl"
    assert handler._default_output_key("shot.mp4") == "shot_bl.mp4"


def test_process_rejects_bad_preset():
    out = handler._process({"job_type": "grade", "preset": "neon_nightmare", "clip_key": "x.mp4"})
    assert out["ok"] is False
    assert "preset" in out["error"]


def test_process_rejects_bad_job_type():
    out = handler._process({"job_type": "bake_bread", "preset": "neutral", "clip_key": "x.mp4"})
    assert out["ok"] is False
    assert "job_type" in out["error"]


def test_process_missing_transport():
    out = handler._process({"job_type": "grade", "preset": "neutral"})
    assert out["ok"] is False
    assert "need" in out["error"].lower() or "R2" in out["error"]


def test_handler_missing_input():
    out = handler.handler({})
    assert out["ok"] is False
