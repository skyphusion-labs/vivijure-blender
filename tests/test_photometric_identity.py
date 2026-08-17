"""Identity-preserving grade must check luma; creative grades must not (cf#567).

Stubs `_mean_luma` so CI needs no ffmpeg. The wiring is the test: identity
calls the luma function, filmic_warm does not, a wrecked identity returns
ok:false and does not upload.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("handler", ROOT / "handler.py")
assert spec and spec.loader
sys.path.insert(0, str(ROOT))
handler = importlib.util.module_from_spec(spec)
sys.modules["handler"] = handler
spec.loader.exec_module(handler)


def test_identity_predicate():
    assert handler._identity_preserving_grade("grade", "neutral", 1.0)
    assert handler._identity_preserving_grade("grade", "filmic_warm", 0.0)
    assert not handler._identity_preserving_grade("grade", "filmic_warm", 1.0)
    assert not handler._identity_preserving_grade("grade", "high_contrast", 1.4)
    assert not handler._identity_preserving_grade("composite", "neutral", 1.0)


def _stub_pipeline(monkeypatch, luma_fn):
    uploads: list[tuple] = []

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
    monkeypatch.setattr(handler, "_upload_url", lambda path, url: uploads.append((path, url)) or 18)
    monkeypatch.setattr(handler, "_url_error", lambda _url, _what: None)
    monkeypatch.setattr(handler, "_r2_client", lambda: None)
    monkeypatch.setattr(handler, "_mean_luma", luma_fn)
    return uploads


def _job(*, preset: str, strength: float = 1.0, job_type: str = "grade") -> dict:
    return {
        "job_type": job_type,
        "preset": preset,
        "strength": strength,
        "video_url": "https://bucket.example/in.mp4",
        "output_url": "https://bucket.example/out.mp4",
        "output_key": "renders/p/clips/shot_bl.mp4",
    }


def test_identity_grade_calls_luma(monkeypatch):
    seen: list[str] = []

    def luma(path):
        seen.append(path)
        return 100.0

    uploads = _stub_pipeline(monkeypatch, luma)
    out = handler._process(_job(preset="neutral", strength=1.0))
    assert out["ok"] is True
    assert len(seen) == 2, seen
    assert any(p.endswith("src.mp4") for p in seen)
    assert any(p.endswith("out.mp4") for p in seen)
    assert len(uploads) == 1


def test_strength_zero_calls_luma(monkeypatch):
    seen: list[str] = []

    def luma(path):
        seen.append(path)
        return 100.0

    _stub_pipeline(monkeypatch, luma)
    out = handler._process(_job(preset="filmic_warm", strength=0.0))
    assert out["ok"] is True
    assert len(seen) == 2


def test_creative_grade_does_not_call_luma(monkeypatch):
    seen: list[str] = []

    def luma(path):
        seen.append(path)
        return 30.0

    uploads = _stub_pipeline(monkeypatch, luma)
    out = handler._process(_job(preset="filmic_warm", strength=1.0))
    assert out["ok"] is True
    assert seen == []
    assert len(uploads) == 1


def test_wrecked_identity_returns_ok_false_and_does_not_upload(monkeypatch):
    def luma(path):
        return 30.0 if path.endswith("out.mp4") else 100.0

    uploads = _stub_pipeline(monkeypatch, luma)
    out = handler._process(_job(preset="neutral", strength=1.0))
    assert out["ok"] is False
    assert "photometric identity" in out["error"]
    assert out["photometric"]["verdict"] == "wrecked"
    assert out["photometric"]["ratio"] == 0.3
    assert uploads == []


def test_luma_decode_failure_is_not_a_pass(monkeypatch):
    def luma(_path):
        raise RuntimeError("photometric identity: no YAVG from src.mp4 (rc=1): ")

    uploads = _stub_pipeline(monkeypatch, luma)
    out = handler._process(_job(preset="neutral", strength=1.0))
    assert out["ok"] is False
    assert "photometric identity" in out["error"]
    assert uploads == []
