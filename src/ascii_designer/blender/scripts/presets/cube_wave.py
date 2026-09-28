"""Grid of pillars rising in a travelling wave, seen through an isometric camera."""

import math

from presets import _common as c


def build(scene, params, ctx):
    c.reset(scene)
    primary, secondary, accent, deep = c.palette(params)
    n, waves, frames = params["grid"], params["waves"], ctx["frames"]
    size = 0.9
    material = c.object_color_material("Pillar", roughness=0.35, emission=0.15)
    import bmesh  # noqa: PLC0415 - Blender-only module

    for i in range(n):
        for j in range(n):
            x, y = (i - (n - 1) / 2), (j - (n - 1) / 2)
            if params["shape"] == "cylinder":
                bm = bmesh.new()
                bmesh.ops.create_cone(
                    bm, cap_ends=True, segments=20, radius1=0.42, radius2=0.42, depth=1.0
                )
                for v in bm.verts:
                    v.co.z += 0.5
                pillar = c.bmesh_object(scene, f"P{i}_{j}", bm, material, smooth=True)
            else:
                pillar = c.box(scene, f"P{i}_{j}", (size, size, 1.0), material, base_origin=True)
            pillar.location = (x, y, 0.0)
            distance = math.hypot(x, y) / (n / 2)
            t = min(1.0, distance)
            pillar.color = c.mix(
                c.mix(accent, primary, min(1.0, t * 1.6)), secondary, max(0.0, t - 0.4)
            )
            offset = 2 * math.pi * waves * distance
            c.drive(
                pillar,
                "scale",
                f"0.35 + 1.6 * (0.5 + 0.5 * sin({c.phase(frames)} - {offset!r}))",
                2,
            )
    scale = n * 1.95
    c.ortho_camera(scene, (n * 1.1, -n * 1.1, n * 1.05), (0, 0, 0.4), scale)
    c.world(scene, c.mix(deep, (1, 1, 1, 1), 0.1), 0.6)
    c.light(scene, "SUN", (-4, -6, 10), (0, 0, 0), (1, 1, 1, 1), 3.5)
    c.light(scene, "AREA", (8, 6, 4), (0, 0, 0), secondary, 900, 8, name="Rim")
    return {"film_transparent": True}
