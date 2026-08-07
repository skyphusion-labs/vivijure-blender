"""The render step must verify its own output (vivijure-blender#4). CPU-only, no Blender.

`blender -b --python script.py` runs the script in its own interpreter and EXITS 0 even
when that script dies on an uncaught exception -- it prints the traceback, says
"Blender quit", and returns 0. So a returncode check is STRUCTURALLY INCAPABLE of seeing
a crashed render, and the only symptom reaches the caller two steps later as an ffmpeg
error about a missing input pattern: the wrong component, named with full confidence.

That is not hypothetical. `vivijure-blender:0.1.0` shipped with five writes to read-only
or non-existent Image-datablock attributes; every job died at the first one, blender
exited 0, and the endpoint has never completed a job (RunPod: completed 0, failed 0).

Two guards here:
  * the gate itself -- frames written, not exit status
  * a source guard for the defect CLASS, since CI has no Blender to run
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("handler", ROOT / "handler.py")
assert spec and spec.loader
handler = importlib.util.module_from_spec(spec)
sys.modules["handler"] = handler
spec.loader.exec_module(handler)


class _Proc:
    """Stand-in for the CompletedProcess blender returns when its script crashed: rc 0."""

    def __init__(self, returncode=0, stdout="Blender quit\n", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _call(tmp_path, monkeypatch, *, frames_to_write, frame_end, rc=0, stderr=""):
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir()

    def fake_run(cmd, **kwargs):
        # Blender's contract as observed: it may write nothing and still exit 0.
        os.makedirs(out_dir, exist_ok=True)
        for i in range(1, frames_to_write + 1):
            (out_dir / f"frame_{i:04d}.png").write_bytes(b"x")
        return _Proc(returncode=rc, stderr=stderr)

    monkeypatch.setattr(handler.subprocess, "run", fake_run)
    handler._run_blender(str(in_dir), str(out_dir), "filmic_warm", 1.0, frame_end, 24.0, None)


def test_zero_frames_on_a_zero_exit_is_refused(tmp_path, monkeypatch):
    """THE DEFECT: rc=0 with nothing rendered used to pass straight through."""
    with pytest.raises(RuntimeError) as e:
        _call(tmp_path, monkeypatch, frames_to_write=0, frame_end=8)
    msg = str(e.value)
    assert "wrote 0 of 8 frames" in msg, msg
    assert "exited 0" in msg, msg


def test_partial_render_on_a_zero_exit_is_refused(tmp_path, monkeypatch):
    """A truncated render is the same class as an empty one and must not pass."""
    with pytest.raises(RuntimeError) as e:
        _call(tmp_path, monkeypatch, frames_to_write=3, frame_end=8)
    assert "wrote 3 of 8 frames" in str(e.value)


def test_blender_stderr_is_carried_into_the_error(tmp_path, monkeypatch):
    """On a ZERO exit blender's output was discarded, so the real cause vanished.

    The traceback naming the file and line is the whole diagnostic value; without it the
    operator is left with an ffmpeg error two steps downstream.
    """
    tb = 'AttributeError: bpy_struct: attribute "frame_duration" from "Image" is read-only'
    with pytest.raises(RuntimeError) as e:
        _call(tmp_path, monkeypatch, frames_to_write=0, frame_end=8, stderr=tb)
    assert tb in str(e.value), "blender's own traceback was dropped from the error"


def test_complete_render_passes(tmp_path, monkeypatch):
    """POSITIVE CONTROL: without this, a gate that refused everything would look correct."""
    _call(tmp_path, monkeypatch, frames_to_write=8, frame_end=8)


def test_extra_frames_do_not_trip_the_gate(tmp_path, monkeypatch):
    """The gate is a floor, not an equality; more frames than asked is not a failure."""
    _call(tmp_path, monkeypatch, frames_to_write=9, frame_end=8)


def test_nonzero_exit_still_refused(tmp_path, monkeypatch):
    """Control: the original returncode check must survive the new one."""
    with pytest.raises(RuntimeError) as e:
        _call(tmp_path, monkeypatch, frames_to_write=8, frame_end=8, rc=1, stderr="boom")
    assert "blender exit 1" in str(e.value)


# --------------------------------------------------------- the defect class itself

# Image-datablock sequence attrs. Measured individually on Blender 4.2.8 LTS:
#   frame_duration -> read-only;  frame_start / frame_offset -> not attributes of Image.
# All three raise on assignment, so framing must be set on the NODE's image_user.
FORBIDDEN = re.compile(r"^\s*\w*img\.(?:frame_duration|frame_start|frame_offset)\s*=", re.M)

COMPOSITE = ROOT / "scripts" / "composite_job.py"


def test_matcher_can_actually_match():
    """POSITIVE CONTROL for the source guard below. A guard that matches nothing would
    report the file clean forever, which is the failure mode it exists to prevent."""
    assert FORBIDDEN.search("    img.frame_duration = n_frames\n")
    assert FORBIDDEN.search("            pimg.frame_start = args.frame_start\n")
    # and must NOT match the node-side writes, which are correct and must survive
    assert not FORBIDDEN.search("    img_node.frame_duration = n_frames\n")
    assert not FORBIDDEN.search("    plate_node.frame_start = args.frame_start\n")


def test_composite_script_writes_no_image_datablock_frame_attrs():
    src = COMPOSITE.read_text()
    hits = FORBIDDEN.findall(src)
    assert not hits, f"Image-datablock frame_* writes reintroduced: {hits}"


def test_node_side_framing_is_still_set():
    """The counterpart: deleting the broken writes must not delete the working ones."""
    src = COMPOSITE.read_text()
    assert re.search(r"^\s*img_node\.frame_duration\s*=", src, re.M)
    assert re.search(r"^\s*img_node\.frame_start\s*=", src, re.M)
    assert re.search(r"^\s*plate_node\.frame_duration\s*=", src, re.M)
