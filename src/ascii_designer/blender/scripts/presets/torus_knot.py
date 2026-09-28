"""Rotating (p, q) torus knot with rim lighting."""

import math

from presets import _common as c


def build(scene, params, ctx):
    c.reset(scene)
    primary, secondary, accent, deep = c.palette(params)
    p, q = params["p"], params["q"]
    samples = 900
    points = []
    for i in range(samples):
        t = 2 * math.pi * i / samples
        r = 2.0 + math.cos(q * t)
        points.append((r * math.cos(p * t), r * math.sin(p * t), -math.sin(q * t)))
    verts, faces = c.tube(points, params["tube"], sides=36)

    look = params["material"]
    if look == "neon":
        material = c.principled(
            "Knot", (0.02, 0.02, 0.02, 1), roughness=0.4, emission=primary, strength=2.5
        )
    elif look == "matte":
        material = c.principled("Knot", primary, roughness=0.55)
    else:
        material = c.principled("Knot", primary, metallic=0.55, roughness=0.32, coat=0.5)
    knot = c.mesh_object(scene, "Knot", verts, faces, material)
    # Spin around the knot's own axis first (Z), then tilt it towards the camera.
    knot.rotation_mode = "ZXY"
    tilt = math.radians(62)
    c.drive(knot, "rotation_euler", c.phase(ctx["frames"], params["turns"]), index=2)
    c.drive(knot, "rotation_euler", f"{tilt!r} + 0.12 * sin({c.phase(ctx['frames'])})", index=0)

    c.world(scene, c.mix(deep, (1, 1, 1, 1), 0.15), strength=0.8)
    c.camera(scene, (0.0, -13.0, 0.0), (0, 0, 0), lens=42)
    c.light(scene, "AREA", (-4.0, -5.0, 5.0), (0, 0, 0), c.mix(accent, (1, 1, 1, 1), 0.6), 1800, 5)
    c.light(scene, "AREA", (5.5, 3.5, 2.0), (0, 0, 0), secondary, 1400, 3, name="Rim")
    c.light(scene, "AREA", (-5.0, 4.0, -2.5), (0, 0, 0), primary, 900, 3, name="Fill")
    return {"film_transparent": True}
