"""Spiral galaxy of emissive stars; rotates by one arm per loop.

Stars are generated for one arm and copied with arm-fold symmetry, so turning
by 2*pi/arms per loop is seamless.
"""

import math
import random

from mathutils import Matrix

from presets import _common as c


def build(scene, params, ctx):
    c.reset(scene)
    primary, secondary, accent, deep = c.palette(params)
    arms, frames = params["arms"], ctx["frames"]
    rng = random.Random(params["seed"])
    import bmesh  # noqa: PLC0415 - Blender-only module

    per_arm = params["stars"] // arms
    layers = {name: bmesh.new() for name in ("core", "inner", "outer")}
    for _ in range(per_arm):
        r = rng.random() ** 0.7 * 5.5
        base = r * 0.9 + rng.gauss(0, 0.28)  # logarithmic-ish spiral
        spread = rng.gauss(0, 0.12 + 0.04 * r)
        z = rng.gauss(0, 0.12 * math.exp(-r / 3))
        size = rng.choice((0.02, 0.03, 0.04, 0.06)) * (1.4 if r < 1 else 1.0)
        layer = "core" if r < 1.2 else ("inner" if r < 3.2 else "outer")
        for k in range(arms):
            a = base + spread + 2 * math.pi * k / arms
            # Turn each copy with its arm, so the field maps onto itself exactly per loop.
            bmesh.ops.create_icosphere(
                layers[layer],
                subdivisions=1,
                radius=size,
                matrix=Matrix.Translation((r * math.cos(a), r * math.sin(a), z))
                @ Matrix.Rotation(2 * math.pi * k / arms, 4, "Z"),
            )
    colors = {
        "core": (c.mix(accent, (1, 1, 1, 1), 0.5), 12.0),
        "inner": (primary, 9.0),
        "outer": (secondary, 7.0),
    }
    import bpy  # noqa: PLC0415

    disc = bpy.data.objects.new("Galaxy", None)
    c.link(disc, scene)
    for name, bm in layers.items():
        color, strength = colors[name]
        stars = c.bmesh_object(
            scene, f"Stars_{name}", bm, c.emissive(name, color, strength), smooth=False
        )
        stars.parent = disc
    glow = c.uv_sphere(  # 60 segments divide evenly by 2..6 arms, so the loop turn is exact
        scene,
        "CoreGlow",
        0.45,
        c.emissive("CoreGlow", c.mix(accent, (1, 1, 1, 1), 0.6), 6.0),
        segments=60,
    )
    glow.parent = disc
    glow.scale = (1.0, 1.0, 0.45)
    disc.rotation_mode = "ZXY"  # spin about the disc's own axis, then tilt toward the camera
    c.drive(disc, "rotation_euler", f"{math.radians(62)!r}", 0)
    c.drive(disc, "rotation_euler", c.loop_value(frames, 2 * math.pi / arms), 2)
    c.world(scene, (0, 0, 0, 1), 0.0)
    c.camera(scene, (0, -13.0, 0.4), (0, 0, 0), lens=36)
    del deep
    return {"film_transparent": True}
