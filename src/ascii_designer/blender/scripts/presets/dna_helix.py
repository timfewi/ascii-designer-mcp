"""Rotating double helix with base-pair rungs."""

import math

from presets import _common as c


def build(scene, params, ctx):
    c.reset(scene)
    primary, secondary, accent, deep = c.palette(params)
    pairs, frames = params["pairs"], ctx["frames"]
    height, radius, twist = 7.4, 1.0, 2.0  # twist: helix turns over the full height
    samples = 480
    strands = []
    for offset, color in ((0.0, primary), (math.pi, secondary)):
        points = []
        for i in range(samples + 1):
            t = i / samples
            a = 2 * math.pi * twist * t + offset
            points.append((radius * math.cos(a), radius * math.sin(a), (t - 0.5) * height))
        verts, faces = c.tube(points, 0.16, sides=16, closed=False)
        material = c.principled("Strand", color, metallic=0.4, roughness=0.3, coat=0.5)
        strands.append(c.mesh_object(scene, "Strand", verts, faces, material))
    rung_mats = [
        c.principled(f"Rung{k}", col, roughness=0.5)
        for k, col in enumerate((accent, c.mix(primary, secondary, 0.5)))
    ]
    rungs = []
    for p in range(pairs):
        t = (p + 0.5) / pairs
        a = 2 * math.pi * twist * t
        z = (t - 0.5) * height
        start = (radius * math.cos(a), radius * math.sin(a), z)
        end = (-start[0], -start[1], z)
        verts, faces = c.tube([start, end], 0.06, sides=10, closed=False)
        rungs.append(c.mesh_object(scene, f"Rung{p}", verts, faces, rung_mats[p % 2]))
    import bpy  # noqa: PLC0415 - Blender-only module

    pivot = bpy.data.objects.new("Helix", None)
    c.link(pivot, scene)
    for obj in strands + rungs:
        obj.parent = pivot
    pivot.rotation_mode = "ZXY"
    c.drive(pivot, "rotation_euler", c.phase(frames, params["turns"]), 2)
    c.drive(pivot, "rotation_euler", f"{math.radians(8)!r}", 0)
    c.drive(pivot, "rotation_euler", f"{math.radians(-32)!r}", 1)
    c.world(scene, c.mix(deep, (0, 0, 0, 1), 0.2), 0.5)
    c.light(scene, "AREA", (-4, -6, 4), (0, 0, 0), (1, 1, 1, 1), 1200, 5)
    c.light(scene, "AREA", (5, 4, -2), (0, 0, 0), accent, 700, 4, name="Rim")
    c.camera(scene, (0, -14.5, 0), (0, 0, 0), lens=35)
    return {"film_transparent": True}
