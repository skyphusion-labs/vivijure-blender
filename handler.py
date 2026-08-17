"""RunPod serverless handler -- Blender headless compositor for Vivijure finish-blender.

Phase-1 satellite: templated compositor jobs only (grade presets + optional plate underlay).
No user-supplied bpy/Python. No free-form .blend upload.

Job input (R2 finish-chain mode -- shared bucket):
  {
    "project":     "<project>",
    "clip_key":    "renders/<project>/clips/<shot>.mp4",
    "output_key":  "renders/<project>/clips/<shot>_bl.mp4",   # optional
    "job_type":    "grade",          # grade | composite
    "preset":      "filmic_warm",
    "strength":    1.0,
    "plate_key":   "..."             # optional; composite underlay plate
  }

Presigned mode also accepted: video_url + output_url + output_key
(+ optional plate_url). output_key is required so the returned clip_key is a
real R2 key; the transport mode name is never a substitute (vivijure-blender#12).

Returns: { ok, shot_id?, clip_key, out_fps, frames, applied, bytes, preset, job_type }
or { ok: false, error } -- the module soft-degrades on non-ok.
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
import subprocess
import tempfile
import time
from typing import Any
from urllib.parse import urlparse, urlunparse

import boto3
import requests
import runpod

BLENDER_BIN = os.environ.get("BLENDER_BIN", "/opt/blender/blender")
COMPOSITE_SCRIPT = os.environ.get(
    "COMPOSITE_SCRIPT", "/app/scripts/composite_job.py"
)
# Studio phase ceiling this door is governed by. Symbol is
# PHASE_HARD_DEADLINE_SECONDS in vivijure-core src/film-model.ts; the value has
# never moved. One attempt that outlives this dies as "stalled, no progress"
# because filmProgressMarker does not count attempts (vivijure-blender#17).
# Do not raise that ceiling to match this door; keep this door under it.
PHASE_HARD_DEADLINE_SECONDS = 5400

# Per-leg caps. `_process` runs these sequentially, so they SUM. Sized so the
# longest path (composite) stays under PHASE_HARD_DEADLINE_SECONDS on attempt 1.
#
# Old defaults (DOWNLOAD/UPLOAD 900, FFMPEG 1200, BLENDER 1800) summed to
# 6180s grade / 8280s composite -- both above the 5400s ceiling, so finish
# could not complete on attempt 1. Blender stays 1800s (the actual work);
# transfer and ffmpeg drop because a MAX_FRAMES=600 clip does not need 15-20
# minutes to copy or encode.
DOWNLOAD_TIMEOUT = int(os.environ.get("DOWNLOAD_TIMEOUT", "300") or "300")
UPLOAD_TIMEOUT = int(os.environ.get("UPLOAD_TIMEOUT", "300") or "300")
FFMPEG_TIMEOUT = int(os.environ.get("FFMPEG_TIMEOUT", "480") or "480")
BLENDER_TIMEOUT = int(os.environ.get("BLENDER_TIMEOUT", "1800") or "1800")
FFPROBE_FPS_TIMEOUT = 60
FFPROBE_COUNT_TIMEOUT = 120
MAX_FRAMES = int(os.environ.get("MAX_FRAMES", "600") or "600")

PRESETS = ("neutral", "filmic_warm", "high_contrast", "cool", "soft")
JOB_TYPES = ("grade", "composite")

# Same measurement as vivijure-cf photometric_gate.RATIO_TOLERANCE (cf#567).
# Meaningful only for identity-preserving grades; creative grades must not use it.
RATIO_TOLERANCE = 0.02
_YAVG_RE = re.compile(r"lavfi\.signalstats\.YAVG=([0-9.eE+-]+)")

# Optional pin for presigned hosts (e.g. ".r2.cloudflarestorage.com"). Empty = skip host-suffix check.
R2_URL_HOST_SUFFIX = os.environ.get("R2_URL_HOST_SUFFIX", "").strip().lower()

# requests / urllib3 exception text embeds the full URL, including the presigned query.
_FULL_URL_QUERY_RE = re.compile(r"(https?://[^\s'\"<>]+)\?[^\s'\"<>]*", re.IGNORECASE)
_LABELED_URL_QUERY_RE = re.compile(r"(url:\s+\S+?)\?[^\s'\"<>]*", re.IGNORECASE)


def _redact_query(text: str | None) -> str | None:
    """Strip query strings so presigned tokens never leave the worker in errors or logs."""
    if not text:
        return text
    s = str(text)
    s = _FULL_URL_QUERY_RE.sub(r"\1?[redacted]", s)
    s = _LABELED_URL_QUERY_RE.sub(r"\1?[redacted]", s)
    return s


def _ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def _resolve_public_ips(host: str) -> list[str]:
    """Resolve host; return public IPs or raise ValueError with a job-facing message."""
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError(f"URL host does not resolve: {e}") from e
    public: list[str] = []
    blocked = False
    for _fam, _type, _proto, _canon, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if _ip_blocked(ip):
            blocked = True
        else:
            public.append(str(ip))
    if blocked or not public:
        raise ValueError("URL resolves to a blocked address")
    return public


def _url_error(url: Any, what: str) -> str | None:
    """Refuse non-https / private / link-local / loopback / optional non-R2 host. Returns err str or None.

    Presigned mode otherwise lets any job submitter drive GET/PUT from the GPU worker (SSRF). Resolve
    the hostname and reject blocked address classes; callers must also pass allow_redirects=False and
    connect to a pre-validated IP (see _pinned_https) so DNS cannot rebind between check and fetch."""
    try:
        p = urlparse(str(url or ""))
    except Exception:  # noqa: BLE001 -- malformed URL is a job error, not a crash
        return f"{what}: malformed URL"
    if p.scheme != "https" or not p.hostname:
        return f"{what}: URL must be https with a hostname"
    host = p.hostname.lower()
    if host == "localhost" or host.endswith(".localhost"):
        return f"{what}: URL host is blocked"
    if R2_URL_HOST_SUFFIX:
        suffix = R2_URL_HOST_SUFFIX if R2_URL_HOST_SUFFIX.startswith(".") else f".{R2_URL_HOST_SUFFIX}"
        bare = suffix.lstrip(".")
        if host != bare and not host.endswith(suffix):
            return f"{what}: URL host must end with {R2_URL_HOST_SUFFIX}"
    try:
        _resolve_public_ips(host)
    except ValueError as e:
        return f"{what}: {e}"
    return None


def _pinned_https(method: str, url: str, *, timeout: int, headers=None, data=None, stream: bool = False):
    """HTTPS GET/PUT that resolves once, rejects private addrs, and connects to that IP (DNS-rebinding safe)."""
    from requests.adapters import HTTPAdapter  # deferred: keeps CPU test stubs light

    class _SniAdapter(HTTPAdapter):
        """Keep TLS SNI / hostname verify on the original host while connecting to a pinned IP."""

        def __init__(self, server_hostname, **kwargs):
            self._server_hostname = server_hostname
            super().__init__(**kwargs)

        def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
            pool_kwargs["assert_hostname"] = self._server_hostname
            pool_kwargs["server_hostname"] = self._server_hostname
            return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)

    p = urlparse(str(url or ""))
    if p.scheme != "https" or not p.hostname:
        raise ValueError("URL must be https with a hostname")
    host = p.hostname.lower()
    ip = _resolve_public_ips(host)[0]
    netloc_host = f"[{ip}]" if ":" in ip else ip
    netloc = f"{netloc_host}:{p.port}" if p.port else netloc_host
    pinned = urlunparse((p.scheme, netloc, p.path or "/", p.params, p.query, ""))
    hdrs = dict(headers or {})
    hdrs["Host"] = host if not p.port else f"{host}:{p.port}"
    session = requests.Session()
    session.mount("https://", _SniAdapter(host))
    return session.request(method, pinned, timeout=timeout, headers=hdrs, data=data,
                           stream=stream, allow_redirects=False)


def declared_budget_seconds(job_type: str = "composite") -> int:
    """Worst-case wall clock for one invocation if every sequential guard is fully consumed.

    This is the number the studio phase ceiling is compared against. It must stay
    strictly under PHASE_HARD_DEADLINE_SECONDS at the defaults (vivijure-blender#17).
    Reads the values this process is running with, not the hardcoded defaults, so
    an env override is visible here rather than a claim about a different deploy.
    """
    n_downloads = 2 if job_type == "composite" else 1
    n_extracts = 2 if job_type == "composite" else 1
    return (
        n_downloads * DOWNLOAD_TIMEOUT
        + n_extracts * FFMPEG_TIMEOUT
        + FFPROBE_FPS_TIMEOUT
        + FFPROBE_COUNT_TIMEOUT
        + BLENDER_TIMEOUT
        + FFMPEG_TIMEOUT  # encode
        + UPLOAD_TIMEOUT
    )


def _budget_error() -> str | None:
    budget = declared_budget_seconds("composite")
    if budget >= PHASE_HARD_DEADLINE_SECONDS:
        return (
            f"declared composite budget {budget}s >= phase ceiling "
            f"{PHASE_HARD_DEADLINE_SECONDS}s; one attempt cannot complete "
            f"(vivijure-blender#17)"
        )
    return None


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _r2_client():
    endpoint = _env("R2_ENDPOINT_URL")
    key = _env("R2_ACCESS_KEY_ID")
    secret = _env("R2_SECRET_ACCESS_KEY")
    if not (endpoint and key and secret):
        return None
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=key,
        aws_secret_access_key=secret,
        region_name="auto",
    )


def _bucket() -> str:
    return _env("R2_BUCKET") or "vivijure"


def _run(cmd: list[str], timeout: int = FFMPEG_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, check=True, capture_output=True, text=True, timeout=timeout
    )


def _probe_fps_frames(path: str) -> tuple[float, int]:
    """ffprobe fps + frame count; defaults 24 / 0 on failure."""
    fps = 24.0
    frames = 0
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=r_frame_rate,nb_frames",
                "-of", "default=noprint_wrappers=1:nokey=1", path,
            ],
            capture_output=True, text=True, timeout=FFPROBE_FPS_TIMEOUT,
        )
        lines = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
        if lines:
            rate = lines[0]
            if "/" in rate:
                a, b = rate.split("/", 1)
                if float(b) != 0:
                    fps = float(a) / float(b)
            elif rate.replace(".", "", 1).isdigit():
                fps = float(rate)
        if len(lines) > 1 and lines[1].isdigit():
            frames = int(lines[1])
    except Exception:
        pass
    if frames <= 0:
        try:
            r = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-count_frames",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=nb_read_frames",
                    "-of", "default=nokey=1:noprint_wrappers=1", path,
                ],
                capture_output=True, text=True, timeout=FFPROBE_COUNT_TIMEOUT,
            )
            n = (r.stdout or "").strip()
            if n.isdigit():
                frames = int(n)
        except Exception:
            pass
    return fps, frames


def _download_url(url: str, dest: str) -> None:
    err = _url_error(url, "download_url")
    if err:
        raise ValueError(err)
    with _pinned_https("GET", url, timeout=DOWNLOAD_TIMEOUT, stream=True) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)


def _download_key(client, key: str, dest: str) -> None:
    client.download_file(_bucket(), key, dest)


def _upload_key(client, path: str, key: str) -> int:
    client.upload_file(path, _bucket(), key)
    return os.path.getsize(path)


def _upload_url(path: str, url: str) -> int:
    err = _url_error(url, "output_url")
    if err:
        raise ValueError(err)
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        r = _pinned_https(
            "PUT", url, data=f, timeout=UPLOAD_TIMEOUT,
            headers={"Content-Type": "video/mp4", "Content-Length": str(size)},
        )
        r.raise_for_status()
    return size


def _default_output_key(clip_key: str) -> str:
    dot = clip_key.rfind(".")
    slash = clip_key.rfind("/")
    if dot > slash:
        return f"{clip_key[:dot]}_bl{clip_key[dot:]}"
    return f"{clip_key}_bl"


def _extract_frames(video: str, out_dir: str) -> int:
    os.makedirs(out_dir, exist_ok=True)
    pattern = os.path.join(out_dir, "%06d.png")
    _run([
        "ffmpeg", "-hide_banner", "-y", "-i", video,
        "-start_number", "1", "-vsync", "0", pattern,
    ], timeout=FFMPEG_TIMEOUT)
    frames = sorted(
        n for n in os.listdir(out_dir)
        if n.endswith(".png") and n[:-4].isdigit()
    )
    if not frames:
        raise RuntimeError("ffmpeg produced no frames")
    if len(frames) > MAX_FRAMES:
        raise RuntimeError(
            f"clip has {len(frames)} frames; MAX_FRAMES={MAX_FRAMES} (trim or raise)"
        )
    return len(frames)


def _identity_preserving_grade(job_type: str, preset: str, strength: float) -> bool:
    """True only when the grade is supposed to preserve luma (cf#567).

    grade + (neutral @ ~1.0, or strength 0 on any preset). Creative grades
    (filmic_warm etc. at nonzero strength) must not be checked.
    """
    if job_type != "grade":
        return False
    if strength == 0.0:
        return True
    return preset == "neutral" and abs(strength - 1.0) <= 1e-6


def _mean_luma(path: str) -> float:
    """Mean luma via ffmpeg signalstats YAVG. Fail loud if the clip cannot be measured."""
    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-nostats",
                "-i", path,
                "-vf", "signalstats,metadata=print:file=-",
                "-an", "-f", "null", "-",
            ],
            capture_output=True, text=True, timeout=FFMPEG_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"photometric identity: ffmpeg failed on {path}: {e}") from e
    text = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    values = [float(m) for m in _YAVG_RE.findall(text)]
    if not values:
        tail = text[-500:]
        raise RuntimeError(
            f"photometric identity: no YAVG from {path} (rc={proc.returncode}): {tail}"
        )
    return sum(values) / len(values)


def _photometric_identity(src: str, out_mp4: str) -> dict[str, Any]:
    """Compare mean luma of src vs encoded out. Decode miss raises, never skip-as-pass."""
    src_luma = _mean_luma(src)
    out_luma = _mean_luma(out_mp4)
    if src_luma <= 0:
        raise RuntimeError(
            f"photometric identity: source luma is non-positive ({src_luma})"
        )
    ratio = out_luma / src_luma
    ok = abs(ratio - 1.0) <= RATIO_TOLERANCE
    return {
        "verdict": "ok" if ok else "wrecked",
        "ratio": round(ratio, 4),
        "tolerance": RATIO_TOLERANCE,
        "src_luma": round(src_luma, 3),
        "output_luma": round(out_luma, 3),
    }


def _encode_video(frame_dir: str, fps: float, audio_src: str | None, out_mp4: str) -> None:
    pattern = os.path.join(frame_dir, "%06d.png")
    # Blender names frame_0001.png when filepath is frame_; also accept bare %06d from us.
    # Our script uses scene.render.filepath = .../frame_ so files are frame_0001.png
    bl_pattern = os.path.join(frame_dir, "frame_%04d.png")
    use = bl_pattern if os.path.isfile(os.path.join(frame_dir, "frame_0001.png")) else pattern
    if use == pattern and not os.path.isfile(os.path.join(frame_dir, "000001.png")):
        # try 4-digit bare
        alt = os.path.join(frame_dir, "%04d.png")
        if os.path.isfile(os.path.join(frame_dir, "0001.png")):
            use = alt

    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-framerate", str(fps),
        "-i", use,
    ]
    if audio_src and os.path.isfile(audio_src):
        cmd += ["-i", audio_src, "-map", "0:v:0", "-map", "1:a:0?", "-c:a", "aac", "-shortest"]
    else:
        cmd += ["-an"]
    cmd += [
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "fast",
        out_mp4,
    ]
    _run(cmd, timeout=FFMPEG_TIMEOUT)


def _run_blender(
    in_dir: str,
    out_dir: str,
    preset: str,
    strength: float,
    frame_end: int,
    fps: float,
    plate_dir: str | None,
) -> None:
    os.makedirs(out_dir, exist_ok=True)
    cmd = [
        BLENDER_BIN, "-b", "--python", COMPOSITE_SCRIPT, "--",
        "--in-dir", in_dir,
        "--out-dir", out_dir,
        "--preset", preset,
        "--strength", str(strength),
        "--frame-start", "1",
        "--frame-end", str(frame_end),
        "--fps", str(fps),
    ]
    if plate_dir:
        cmd += ["--plate-dir", plate_dir]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=BLENDER_TIMEOUT,
    )
    if proc.returncode != 0:
        tail = ((proc.stderr or "") + "\n" + (proc.stdout or ""))[-2000:]
        raise RuntimeError(f"blender exit {proc.returncode}: {tail}")

    # A zero exit is NOT evidence that anything rendered. `blender -b --python` runs the
    # script inside its own interpreter and EXITS 0 even when that script dies on an
    # uncaught exception: it prints the traceback, says "Blender quit", and returns 0.
    # So the returncode check above is structurally incapable of seeing a script that
    # crashed, and the only symptom reaches the caller two steps later as an ffmpeg error
    # about a missing input pattern -- naming the wrong component with full confidence
    # (vivijure-blender#4, which is exactly how a read-only bpy attribute presented).
    # Verify the ARTIFACT the step exists to produce, and carry blender's own output into
    # the error, because on a zero exit it is otherwise discarded.
    produced = sorted(
        n for n in os.listdir(out_dir)
        if n.startswith("frame_") and n.endswith(".png")
    )
    expected = frame_end  # rendered 1..frame_end inclusive; see --frame-start above
    if len(produced) < expected:
        tail = ((proc.stderr or "") + "\n" + (proc.stdout or ""))[-2000:]
        raise RuntimeError(
            f"blender exited 0 but wrote {len(produced)} of {expected} frames "
            f"to {out_dir}: {tail}"
        )


def _selftest() -> dict[str, Any]:
    """No network: prove blender + ffmpeg are wired."""
    if not os.path.isfile(BLENDER_BIN):
        return {"ok": False, "error": f"BLENDER_BIN missing: {BLENDER_BIN}"}
    try:
        v = subprocess.run(
            [BLENDER_BIN, "-b", "--version"],
            capture_output=True, text=True, timeout=60,
        )
        ver = (v.stdout or v.stderr or "").splitlines()[:3]
    except Exception as e:
        return {"ok": False, "error": f"blender --version failed: {e}"}
    try:
        ff = subprocess.run(
            ["ffmpeg", "-hide_banner", "-version"],
            capture_output=True, text=True, timeout=30,
        )
        ff_ok = ff.returncode == 0
    except Exception:
        ff_ok = False
    with tempfile.TemporaryDirectory(prefix="vj-bl-selftest-") as td:
        # 8-frame solid via ffmpeg
        src = os.path.join(td, "src.mp4")
        _run([
            "ffmpeg", "-hide_banner", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=0.5:r=16",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", src,
        ], timeout=60)
        in_dir = os.path.join(td, "in")
        out_dir = os.path.join(td, "out")
        n = _extract_frames(src, in_dir)
        _run_blender(in_dir, out_dir, "filmic_warm", 1.0, n, 16.0, None)
        out_mp4 = os.path.join(td, "out.mp4")
        _encode_video(out_dir, 16.0, None, out_mp4)
        if not os.path.isfile(out_mp4) or os.path.getsize(out_mp4) < 100:
            return {"ok": False, "error": "selftest produced empty output"}
    return {
        "ok": True,
        "blender": ver,
        "ffmpeg": ff_ok,
        "frames": n,
        "applied": ["selftest:grade:filmic_warm"],
    }


def _process(job: dict[str, Any]) -> dict[str, Any]:
    if job.get("selftest"):
        return _selftest()

    job_type = str(job.get("job_type") or "grade").lower()
    if job_type not in JOB_TYPES:
        return {"ok": False, "error": f"unknown job_type {job_type!r}; want {JOB_TYPES}"}
    preset = str(job.get("preset") or "filmic_warm")
    if preset not in PRESETS:
        return {"ok": False, "error": f"unknown preset {preset!r}; want {PRESETS}"}
    try:
        strength = float(job.get("strength", 1.0))
    except (TypeError, ValueError):
        strength = 1.0
    strength = max(0.0, min(2.0, strength))

    # Env overrides can recreate the #17 stall. Refuse before any download so a
    # mis-sized deploy fails loud instead of running past the phase ceiling.
    budget_err = _budget_error()
    if budget_err:
        return {"ok": False, "error": budget_err}

    clip_key = job.get("clip_key") or ""
    output_key = job.get("output_key") or (
        _default_output_key(clip_key) if clip_key else ""
    )
    video_url = job.get("video_url") or ""
    output_url = job.get("output_url") or ""
    plate_key = job.get("plate_key") or ""
    plate_url = job.get("plate_url") or ""
    shot_id = job.get("shot_id") or ""
    project = job.get("project") or ""

    r2 = _r2_client()
    use_r2 = bool(clip_key) and r2 is not None
    if use_r2 and not _env("R2_ENDPOINT_URL"):
        return {
            "ok": False,
            "error": "R2 mode needs R2_ENDPOINT_URL + R2_ACCESS_KEY_ID/SECRET in the endpoint env",
        }
    if not use_r2 and not (video_url and output_url):
        if clip_key and r2 is None:
            return {
                "ok": False,
                "error": "R2 mode needs R2_ENDPOINT_URL + R2_ACCESS_KEY_ID/SECRET in the endpoint env",
            }
        return {
            "ok": False,
            "error": "need clip_key (R2) or video_url+output_url (presigned)",
        }
    if not output_key:
        return {
            "ok": False,
            "error": "need output_key (or clip_key to derive one); clip_key cannot be a transport-mode name",
        }

    if not use_r2:
        for u, name in ((video_url, "video_url"), (output_url, "output_url"),
                        (plate_url, "plate_url")):
            if name == "plate_url" and not u:
                continue
            err = _url_error(u, name)
            if err:
                return {"ok": False, "error": err}

    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="vj-blender-") as td:
        src = os.path.join(td, "src.mp4")
        if use_r2:
            assert r2 is not None
            _download_key(r2, clip_key, src)
        else:
            _download_url(video_url, src)

        plate_dir = None
        if job_type == "composite" and (plate_key or plate_url):
            plate_vid = os.path.join(td, "plate.mp4")
            if plate_key and r2 is not None:
                _download_key(r2, plate_key, plate_vid)
            elif plate_url:
                _download_url(plate_url, plate_vid)
            else:
                return {"ok": False, "error": "composite needs plate_key or plate_url"}
            plate_dir = os.path.join(td, "plate_frames")
            _extract_frames(plate_vid, plate_dir)

        in_dir = os.path.join(td, "in")
        out_dir = os.path.join(td, "out")
        n = _extract_frames(src, in_dir)
        fps, probed = _probe_fps_frames(src)
        if probed > 0:
            n = min(n, probed)

        _run_blender(in_dir, out_dir, preset, strength, n, fps, plate_dir)

        out_mp4 = os.path.join(td, "out.mp4")
        _encode_video(out_dir, fps, src, out_mp4)

        if _identity_preserving_grade(job_type, preset, strength):
            try:
                gate = _photometric_identity(src, out_mp4)
            except RuntimeError as e:
                return {"ok": False, "error": str(e)}
            if gate["verdict"] == "wrecked":
                return {
                    "ok": False,
                    "error": (
                        f"photometric identity wrecked: ratio {gate['ratio']} "
                        f"outside +/-{gate['tolerance']}"
                    ),
                    "photometric": gate,
                }

        size = os.path.getsize(out_mp4)

        if use_r2:
            assert r2 is not None and output_key
            _upload_key(r2, out_mp4, output_key)
        else:
            _upload_url(out_mp4, output_url)
        result_key = output_key

    applied = [f"blender:{job_type}:{preset}"]
    if strength != 1.0:
        applied.append(f"strength:{strength:g}")
    return {
        "ok": True,
        "shot_id": shot_id or None,
        "clip_key": result_key,
        "out_fps": fps,
        "frames": n,
        "applied": applied,
        "bytes": size,
        "preset": preset,
        "job_type": job_type,
        "project": project or None,
        "elapsed_s": round(time.time() - t0, 2),
    }


def handler(event: dict[str, Any]) -> dict[str, Any]:
    try:
        job = event.get("input") if isinstance(event, dict) else None
        if not isinstance(job, dict):
            return {"ok": False, "error": "missing input object"}
        return _process(job)
    except subprocess.TimeoutExpired as e:
        return {"ok": False, "error": _redact_query(f"timeout: {e}")}
    except Exception as e:  # noqa: BLE001 -- surface as data for module soft-degrade
        return {"ok": False, "error": _redact_query(f"{type(e).__name__}: {e}")}


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
