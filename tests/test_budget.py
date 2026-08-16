"""Declared finish-guard budget must fit inside the studio phase ceiling (#17).

`_process` runs download, extract, probe, blender, encode, upload sequentially
in one invocation, so the per-leg caps SUM. Before this change the defaults
summed to 6180s (grade) / 8280s (composite) against
PHASE_HARD_DEADLINE_SECONDS = 5400, so finish could not complete on attempt 1
and the film died as "stalled, no progress".

A test that only asserts a short job still succeeds cannot see this: the
defect is arithmetic, not a crash. These tests assert the ordering, that
the helper uses the running values (env-overridable), and that a mis-sized
override is refused before any work starts.
"""
from __future__ import annotations

import ast
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

# The numbers #17 measured at 4fa33fe. A later bump that recreates that
# ordering must fail this file, not only a comment.
OLD_GRADE_S = 6180
OLD_COMPOSITE_S = 8280
PHASE_HARD_DEADLINE_S = 5400


def test_phase_ceiling_constant_matches_core():
    # The door names the ceiling it is governed by so a later edit cannot
    # quietly retarget a different number.
    assert handler.PHASE_HARD_DEADLINE_SECONDS == PHASE_HARD_DEADLINE_S


def test_default_grade_budget_fits_under_the_phase_ceiling():
    budget = handler.declared_budget_seconds("grade")
    assert budget < PHASE_HARD_DEADLINE_S, (
        f"grade declared budget {budget}s must be under the {PHASE_HARD_DEADLINE_S}s "
        f"phase ceiling so one attempt can complete (vivijure-blender#17). "
        f"Do not raise the core ceiling to match this door."
    )
    assert budget < OLD_GRADE_S, f"grade budget {budget}s did not actually shrink from {OLD_GRADE_S}"


def test_default_composite_budget_fits_under_the_phase_ceiling():
    budget = handler.declared_budget_seconds("composite")
    assert budget < PHASE_HARD_DEADLINE_S, (
        f"composite declared budget {budget}s must be under the {PHASE_HARD_DEADLINE_S}s "
        f"phase ceiling so one attempt can complete (vivijure-blender#17). "
        f"Do not raise the core ceiling to match this door."
    )
    assert budget < OLD_COMPOSITE_S, (
        f"composite budget {budget}s did not actually shrink from {OLD_COMPOSITE_S}"
    )


def test_composite_is_the_longest_declared_path():
    # The refusal in _process keys off composite. If grade ever became the
    # longer path, that check would go green over a still-broken door.
    assert handler.declared_budget_seconds("composite") > handler.declared_budget_seconds("grade")


def test_budget_uses_the_running_values_not_a_frozen_literal(monkeypatch):
    # #17: a manifest constant standing in for a value the deployment can
    # change is a claim about a different deployment.
    base = handler.declared_budget_seconds("grade")
    monkeypatch.setattr(handler, "DOWNLOAD_TIMEOUT", handler.DOWNLOAD_TIMEOUT + 50)
    assert handler.declared_budget_seconds("grade") == base + 50


def test_process_refuses_when_running_budget_exceeds_the_ceiling(monkeypatch):
    # Drive it red the way production would: env-style override of a leg so
    # the sequential sum crosses 5400, then assert the door returns instead
    # of starting a job that cannot finish inside the phase.
    monkeypatch.setattr(handler, "BLENDER_TIMEOUT", 10_000)
    assert handler.declared_budget_seconds("composite") >= PHASE_HARD_DEADLINE_S
    out = handler._process({"job_type": "grade", "preset": "neutral", "clip_key": "x.mp4"})
    assert out["ok"] is False
    assert "error" in out
    assert "5400" in out["error"]
    assert "budget" in out["error"]


def test_default_running_budget_is_not_refused():
    # The other direction: a guard that refused every job would still pass
    # the oversized-override test above.
    assert handler._budget_error() is None
    out = handler._process({"job_type": "grade", "preset": "neutral", "clip_key": "x.mp4"})
    # Missing R2 creds, not a budget refusal.
    assert out["ok"] is False
    assert "budget" not in out["error"]


def test_probe_timeouts_are_the_named_constants():
    # The 60s / 120s ffprobe legs are in the #17 sum. If they go back to
    # magic numbers the helper can drift from the call sites.
    src = (ROOT / "handler.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    probe_fn = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_probe_fps_frames"
    )
    timeouts = []
    for node in ast.walk(probe_fn):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "timeout" and isinstance(kw.value, ast.Name):
                    timeouts.append(kw.value.id)
    assert timeouts == ["FFPROBE_FPS_TIMEOUT", "FFPROBE_COUNT_TIMEOUT"], timeouts
