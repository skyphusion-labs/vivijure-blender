"""Presigned URL SSRF gate + query redaction (no Blender / GPU / network)."""
from __future__ import annotations

import importlib.util
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("handler", ROOT / "handler.py")
assert spec and spec.loader
sys.path.insert(0, str(ROOT))
handler = importlib.util.module_from_spec(spec)
sys.modules["handler"] = handler
spec.loader.exec_module(handler)


def _public_addrinfo(host, port, *a, **k):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))]


def test_url_error_rejects_http_and_private(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))])
    assert handler._url_error("http://evil.example/x", "video_url")
    assert handler._url_error("https://127.0.0.1/x", "video_url")
    assert "blocked" in handler._url_error("https://loop.example/x", "video_url")
    assert "blocked" in handler._url_error("https://localhost/x", "video_url")


def test_url_error_rejects_link_local_metadata(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443))])
    assert "blocked" in handler._url_error("https://metadata.example/latest", "video_url")


def test_url_error_accepts_public_https(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_addrinfo)
    assert handler._url_error("https://bucket.example/obj", "video_url") is None


def test_url_error_host_suffix_pin(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_addrinfo)
    monkeypatch.setattr(handler, "R2_URL_HOST_SUFFIX", ".r2.cloudflarestorage.com")
    assert handler._url_error("https://evil.example/x", "video_url")
    assert handler._url_error(
        "https://acct.r2.cloudflarestorage.com/obj", "video_url") is None


def test_pinned_https_connects_to_resolved_ip(monkeypatch):
    seen = {}

    class _Session:
        def mount(self, prefix, adapter):
            pass

        def request(self, method, url, **k):
            seen["method"] = method
            seen["url"] = url
            seen["k"] = k
            return object()

    monkeypatch.setattr(socket, "getaddrinfo", _public_addrinfo)
    monkeypatch.setattr(handler.requests, "Session", lambda: _Session())
    handler._pinned_https("GET", "https://bucket.example/obj", timeout=1, stream=True)
    assert seen["method"] == "GET"
    assert seen["url"].startswith("https://8.8.8.8/")
    assert seen["k"]["headers"]["Host"] == "bucket.example"
    assert seen["k"]["allow_redirects"] is False


def test_process_rejects_bad_url_before_io(monkeypatch):
    called = {"pin": 0}

    def boom(*a, **k):
        called["pin"] += 1
        raise AssertionError("_pinned_https must not run for rejected URLs")

    monkeypatch.setattr(handler, "_pinned_https", boom)
    out = handler._process({
        "job_type": "grade",
        "preset": "neutral",
        "video_url": "http://169.254.169.254/latest",
        "output_url": "https://bucket.example/o",
        "output_key": "renders/p/clips/shot_bl.mp4",
    })
    assert out["ok"] is False and "error" in out
    assert "https" in out["error"]
    assert called["pin"] == 0


def test_redact_query_strips_presigned_tokens():
    leaked = (
        "403 Client Error: Forbidden for url: "
        "https://acct.r2.cloudflarestorage.com/obj?X-Amz-Signature=deadbeef&X-Amz-Credential=AKIA"
    )
    out = handler._redact_query(leaked)
    assert "deadbeef" not in out
    assert "AKIA" not in out
    assert "X-Amz-Signature" not in out
    assert "[redacted]" in out
    assert "https://acct.r2.cloudflarestorage.com/obj" in out


def test_handler_error_redacts_presigned_query(monkeypatch):
    def boom(job):
        raise RuntimeError(
            "403 for url: https://r2.example/clip.mp4?X-Amz-Signature=deadbeef"
        )

    monkeypatch.setattr(handler, "_process", boom)
    out = handler.handler({"input": {"job_type": "grade"}})
    assert out["ok"] is False
    assert "deadbeef" not in out["error"]
    assert "X-Amz-Signature" not in out["error"]
    assert "[redacted]" in out["error"]


def test_control_redact_can_see_a_token():
    """Positive control: without this, a broken matcher and a leak look the same."""
    leaked = "https://r2.example/x?X-Amz-Signature=deadbeef"
    assert "deadbeef" in leaked
    assert "deadbeef" not in handler._redact_query(leaked)
