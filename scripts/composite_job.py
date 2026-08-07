"""Headless Blender compositor job for vivijure-blender.

Invoked as:
  blender -b --python /app/scripts/composite_job.py -- \\
    --in-dir /work/in --out-dir /work/out --preset filmic_warm \\
    [--plate-dir /work/plate] [--strength 1.0]

Reads a zero-padded PNG sequence from --in-dir, runs a fixed node graph
(template presets only -- no user Python), writes PNG sequence to --out-dir.
Optional --plate-dir alpha-overs the plate under the main clip (simple insert).
"""
from __future__ import annotations

import argparse
import os
import sys


# Preset tables: (gamma, lift_rgb, gain_rgb, saturation)
# Values are gentle; strength scales the delta from neutral.
PRESETS: dict[str, tuple[float, tuple[float, float, float], tuple[float, float, float], float]] = {
    "neutral": (1.0, (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), 1.0),
    "filmic_warm": (0.95, (0.02, 0.01, 0.0), (1.05, 1.0, 0.92), 1.05),
    "high_contrast": (0.9, (-0.02, -0.02, -0.02), (1.12, 1.12, 1.12), 1.1),
    "cool": (1.0, (0.0, 0.01, 0.03), (0.95, 1.0, 1.08), 1.0),
    "soft": (1.05, (0.03, 0.03, 0.03), (0.95, 0.95, 0.95), 0.92),
}


def _parse_args(argv: list[str]) -> argparse.Namespace:
    # Blender leaves a bare "--" before our flags.
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    p = argparse.ArgumentParser(description="vivijure-blender compositor job")
    p.add_argument("--in-dir", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--preset", default="filmic_warm", choices=sorted(PRESETS.keys()))
    p.add_argument("--strength", type=float, default=1.0)
    p.add_argument("--plate-dir", default="")
    p.add_argument("--frame-start", type=int, default=1)
    p.add_argument("--frame-end", type=int, required=True)
    p.add_argument("--fps", type=float, default=24.0)
    return p.parse_args(argv)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _mix_preset(name: str, strength: float):
    gamma, lift, gain, sat = PRESETS[name]
    s = max(0.0, min(2.0, strength))
    # strength 0 = identity; 1 = full preset
    g = _lerp(1.0, gamma, s)
    li = tuple(_lerp(0.0, c, s) for c in lift)
    ga = tuple(_lerp(1.0, c, s) for c in gain)
    sa = _lerp(1.0, sat, s)
    return g, li, ga, sa


def main() -> int:
    import bpy  # type: ignore  # only available inside Blender

    args = _parse_args(sys.argv)
    in_dir = os.path.abspath(args.in_dir)
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    # Fresh scene -- no default cube waste.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT" if hasattr(bpy.types, "EEVEE") else "BLENDER_WORKBENCH"
    # Compositor-only path: we never call Cycles. Engine choice is for scene validity.
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.fps = max(1, int(round(args.fps)))
    scene.frame_start = args.frame_start
    scene.frame_end = args.frame_end
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = os.path.join(out_dir, "frame_")
    scene.render.use_compositing = True
    scene.render.use_sequencer = False
    scene.use_nodes = True

    tree = scene.node_tree
    tree.nodes.clear()

    # Image sequence for the main clip.
    img_node = tree.nodes.new("CompositorNodeImage")
    # Load first frame; set sequence properties.
    first = os.path.join(in_dir, f"{args.frame_start:06d}.png")
    if not os.path.isfile(first):
        # try 0-based
        first = os.path.join(in_dir, f"{0:06d}.png")
    if not os.path.isfile(first):
        print(f"ERROR: no frame at {first}", file=sys.stderr)
        return 2
    img = bpy.data.images.load(first)
    img.source = "SEQUENCE"
    n_frames = args.frame_end - args.frame_start + 1
    # Sequence framing belongs on the NODE's image_user (set immediately below), NEVER on the
    # Image datablock. Measured individually on Blender 4.2.8 LTS (vivijure-blender#4):
    #   img.frame_duration -> AttributeError, "read-only"
    #   img.frame_start    -> AttributeError, no such attribute on Image
    #   img.frame_offset   -> AttributeError, no such attribute on Image
    # All three raised, so deleting only the first would have moved the crash one line down.
    img_node.image = img
    img_node.frame_duration = n_frames
    img_node.frame_start = args.frame_start
    img_node.frame_offset = 0

    gamma, lift, gain, sat = _mix_preset(args.preset, args.strength)

    # Color balance (lift / gamma / gain style via Color Balance node if present).
    color = tree.nodes.new("CompositorNodeColorBalance")
    # Blender color balance: lift, gamma, gain as RGB
    try:
        color.correction_method = "LIFT_GAMMA_GAIN"
    except Exception:
        pass
    try:
        color.lift = lift
        color.gamma = (gamma, gamma, gamma)
        color.gain = gain
    except Exception:
        # Older/newer API: set via inputs
        pass

    sat_node = tree.nodes.new("CompositorNodeHueSat")
    try:
        sat_node.inputs["Saturation"].default_value = sat
    except Exception:
        try:
            sat_node.color_saturation = sat
        except Exception:
            pass

    comp = tree.nodes.new("CompositorNodeComposite")

    links = tree.links
    links.new(img_node.outputs["Image"], color.inputs["Image"])
    links.new(color.outputs["Image"], sat_node.inputs["Image"])
    last = sat_node.outputs["Image"]

    if args.plate_dir:
        plate_dir = os.path.abspath(args.plate_dir)
        pfirst = os.path.join(plate_dir, f"{args.frame_start:06d}.png")
        if not os.path.isfile(pfirst):
            pfirst = os.path.join(plate_dir, f"{0:06d}.png")
        if os.path.isfile(pfirst):
            plate_node = tree.nodes.new("CompositorNodeImage")
            pimg = bpy.data.images.load(pfirst)
            pimg.source = "SEQUENCE"
            # Same read-only/absent Image attrs as the main clip above; the plate's framing
            # is set on plate_node (its image_user) two lines down.
            plate_node.image = pimg
            plate_node.frame_duration = n_frames
            plate_node.frame_start = args.frame_start
            alpha = tree.nodes.new("CompositorNodeAlphaOver")
            links.new(plate_node.outputs["Image"], alpha.inputs[1])  # background
            links.new(last, alpha.inputs[2])  # foreground
            last = alpha.outputs["Image"]

    links.new(last, comp.inputs["Image"])

    # Drive resolution from first frame size.
    try:
        w, h = img.size
        if w > 0 and h > 0:
            scene.render.resolution_x = int(w)
            scene.render.resolution_y = int(h)
    except Exception:
        pass

    bpy.ops.render.render(animation=True)
    print(f"OK: rendered frames {args.frame_start}..{args.frame_end} preset={args.preset}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
