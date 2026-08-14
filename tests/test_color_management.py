"""The compositor must set colour management EXPLICITLY (vivijure-blender#14).

WHY THIS IS A SOURCE GUARD AND NOT A RENDER TEST. CI has no Blender, and the defect is
invisible to every gate this repo already owns: the job exits 0, writes the right frame
count, produces a structurally valid mp4 of the right dimensions and duration, and the
existing render-verification gate passes on all of it. The only symptom is that the
PIXELS are wrong -- so nothing short of decoding a real render can catch it downstream,
and the cheapest honest gate is to assert the source sets the thing at all.

THE DEFECT. Blender 4.x defaults `scene.view_settings.view_transform` to "AgX", a filmic
tone mapper for scene-linear HDR renders. This job's input is DISPLAY-REFERRED footage
(PNG frames ffmpeg pulled out of a finished h264 clip), so the default re-tonemaps an
already-tonemapped image on the way out to PNG. It happens AFTER the compositor, so it
applies identically to every preset and cannot be tuned away in the preset table.

MEASURED, live door render 2026-08-14 (film-a0f533e0, preset=high_contrast strength=1.4):
frame 48 went YAVG 106.71 -> 30.22 with a heavy red shift, from a preset table whose
strongest term is gamma 0.9 / gain 1.12.

Each assertion below names WHICH setting is missing rather than merely failing, so a red
run is evidence rather than a puzzle.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "composite_job.py"


def _src() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_matcher_can_actually_match():
    """POSITIVE CONTROL. Every assertion below is a search for a string; if the file
    cannot be read, or the matcher is anchored wrong, they would all pass vacuously and
    report a clean guard over a broken script. Anchor on something that IS present."""
    src = _src()
    assert "CompositorNodeColorBalance" in src, "control failed: source not readable as expected"
    assert re.search(r"^\s*scene\.render\.use_compositing\s*=\s*True", src, re.M), (
        "control failed: the scene-setup block this guard reasons about is not where expected"
    )


@pytest.mark.parametrize(
    "setting,expected",
    [
        ("scene.view_settings.view_transform", '"Standard"'),
        ("scene.view_settings.look", '"None"'),
        ("scene.display_settings.display_device", '"sRGB"'),
    ],
)
def test_colour_management_is_set_explicitly(setting, expected):
    src = _src()
    pattern = re.escape(setting) + r"\s*=\s*" + re.escape(expected)
    assert re.search(pattern, src), (
        f"{setting} is not pinned to {expected}. Blender's DEFAULT view transform on 4.x "
        f"is AgX, which re-tonemaps display-referred input and silently wrecks every "
        f"preset. Set it explicitly."
    )


def test_view_transform_is_not_wrapped_in_a_swallowing_try():
    """A try/except around the colour-management writes would restore the exact failure
    mode this guard exists to remove: the setting silently not applied, the job exiting 0,
    and a wrong grade shipping as a clean run. The node-property writes below it use
    try/except on purpose (API variance across Blender versions); these must not."""
    src = _src()
    m = re.search(r"scene\.view_settings\.view_transform\s*=", src)
    assert m, "view_transform assignment not found at all"
    # Walk back to the nearest preceding non-blank, non-comment line.
    head = src[: m.start()].rstrip().splitlines()
    prev = ""
    for line in reversed(head):
        s = line.strip()
        if s and not s.startswith("#"):
            prev = s
            break
    assert not prev.startswith("try:"), (
        "colour management is inside a try: block -- a swallowed failure here renders a "
        "wrong grade and reports success"
    )


def test_preset_table_is_gentle_so_a_big_shift_indicts_the_pipeline():
    """Pins the premise the defect analysis rests on: no preset can, on its own, produce a
    3x luma change. If someone later makes a preset genuinely aggressive, this fails and
    the reasoning in the guard above must be revisited rather than silently outdated."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("composite_job", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # safe: main() is guarded, bpy imported inside main()

    for name, (gamma, lift, gain, sat) in mod.PRESETS.items():
        assert 0.8 <= gamma <= 1.25, f"{name}: gamma {gamma} outside the gentle band"
        assert all(abs(c) <= 0.1 for c in lift), f"{name}: lift {lift} outside the gentle band"
        assert all(0.85 <= c <= 1.25 for c in gain), f"{name}: gain {gain} outside the gentle band"
        assert 0.8 <= sat <= 1.25, f"{name}: saturation {sat} outside the gentle band"
