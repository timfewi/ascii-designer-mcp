"""Nested rings spinning on alternating axes around a glowing core."""

import math

from presets import _common as c


def build(scene, params, ctx):
    c.reset(scene)
    primary, secondary, accent, deep = c.palette(params)
    frames = ctx["frames"]
    count = params["rings"]
    axes = ("rotation_euler",)
    del axes
    for k in range(count):
        radius = 1.2 + 0.55 * k
        points = c.closed_polygon(0, radius, 32)
        verts, faces = c.tube(points, 0.07 + 0.015 * k, sides=16, closed=True)
        color = c.mix(primary, secondary, k / max(1, count - 1))
        material = c.principled(f"Ring{k}", color, metallic=0.7, roughness=0.25, coat=0.3)
        ring = c.mesh_object(scene, f"Ring{k}", verts, faces, material)
        ring.rotation_mode = "XYZ"
        # Each ring spins a whole number of turns about its own axis per loop.
        axis = k % 3
        turns = (1 + k % 2) * (-1 if k % 2 else 1)
        c.drive(ring, "rotation_euler", c.phase(frames, turns), axis)
        c.drive(ring, "rotation_euler", f"{math.radians(35 * (k + 1))!r}", (axis + 1) % 3)
    core = c.uv_sphere(
        scene, "Core", 0.55, c.emissive("Core", c.mix(accent, (1, 1, 1, 1), 0.3), 5.0)
    )
    c.drive(core, "scale", f"1 + 0.08 * sin({c.phase(frames, 2)})", 0)
    c.drive(core, "scale", f"1 + 0.08 * sin({c.phase(frames, 2)})", 1)
    c.drive(core, "scale", f"1 + 0.08 * sin({c.phase(frames, 2)})", 2)
    c.light(scene, "POINT", (0, 0, 0), (0, 0, 1), c.mix(accent, (1, 1, 1, 1), 0.5), 800, 0.5)
    c.light(scene, "AREA", (-5, -6, 5), (0, 0, 0), (1, 1, 1, 1), 700, 5, name="Key")
    c.world(scene, c.mix(deep, (0, 0, 0, 1), 0.3), 0.4)
    reach = 1.2 + 0.55 * (count - 1) + 0.3
    c.camera(scene, (0, -reach * 3.6, reach * 0.6), (0, 0, 0), lens=40)
    return {"film_transparent": True}
