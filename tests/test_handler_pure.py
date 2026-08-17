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


def test_handler_source_never_substitutes_presigned_as_clip_key():
    """#12: a mode name is not an R2 key. The old `output_key or "presigned"`
    collapsed "wrote key K" and "wrote something, cannot say where" into one
    truthy string the studio accepted as a clip_key."""
    src = (ROOT / "handler.py").read_text()
    assert 'or "presigned"' not in src
    assert "or 'presigned'" not in src


def test_presigned_without_output_key_refuses_before_io(monkeypatch):
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("must not fetch before output_key is known")

    monkeypatch.setattr(handler, "_download_url", boom)
    if hasattr(handler, "_pinned_get"):
        monkeypatch.setattr(handler, "_pinned_get", boom)
    out = handler._process({
        "job_type": "grade",
        "preset": "neutral",
        "video_url": "https://bucket.example/in.mp4",
        "output_url": "https://bucket.example/out.mp4",
    })
    assert out["ok"] is False
    assert "output_key" in out["error"]
    assert called["n"] == 0


def _stub_presigned_pipeline(monkeypatch):
    """Skip ffmpeg/blender/network; prove the returned clip_key is the written key."""
    def fake_download(_url, dest):
        Path(dest).write_bytes(b"src-bytes")

    def fake_extract(_video, out_dir):
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        return 2

    def fake_encode(_frame_dir, _fps, _audio_src, out_mp4):
        Path(out_mp4).write_bytes(b"mp4-bytes-xxxxxxxx")

    monkeypatch.setattr(handler, "_download_url", fake_download)
    monkeypatch.setattr(handler, "_extract_frames", fake_extract)
    monkeypatch.setattr(handler, "_probe_fps_frames", lambda _p: (24.0, 2))
    monkeypatch.setattr(handler, "_run_blender", lambda *_a, **_k: None)
    monkeypatch.setattr(handler, "_encode_video", fake_encode)
    monkeypatch.setattr(handler, "_upload_url", lambda _path, _url: 18)
    monkeypatch.setattr(handler, "_url_error", lambda _url, _what: None)
    monkeypatch.setattr(handler, "_r2_client", lambda: None)
    # Neutral @ 1.0 is an identity grade; these tests prove clip_key, not luma.
    monkeypatch.setattr(handler, "_mean_luma", lambda _p: 100.0)


def test_presigned_returns_output_key_not_mode_name(monkeypatch):
    _stub_presigned_pipeline(monkeypatch)
    written = "renders/p/clips/shot_bl.mp4"
    out = handler._process({
        "job_type": "grade",
        "preset": "neutral",
        "video_url": "https://bucket.example/in.mp4",
        "output_url": "https://bucket.example/out.mp4",
        "output_key": written,
    })
    assert out["ok"] is True
    assert out["clip_key"] == written
    assert out["clip_key"] != "presigned"


def test_presigned_derives_output_key_from_clip_key(monkeypatch):
    _stub_presigned_pipeline(monkeypatch)
    out = handler._process({
        "job_type": "grade",
        "preset": "neutral",
        "clip_key": "renders/p/clips/shot.mp4",
        "video_url": "https://bucket.example/in.mp4",
        "output_url": "https://bucket.example/out.mp4",
    })
    # No R2 creds in this process, so clip_key is only used to name the output.
    assert out["ok"] is True
    assert out["clip_key"] == "renders/p/clips/shot_bl.mp4"
