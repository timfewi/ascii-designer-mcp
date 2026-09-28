"""Strange attractor traced as a tube, slowly orbiting once per loop."""

import math

from presets import _common as c


def _trace(kind, steps=9000):
    x, y, z = 0.1, 0.0, 0.0
    points = []
    for i in range(steps + 400):
        if kind == "lorenz":
            dt = 0.006
            dx, dy, dz = 10 * (y - x), x * (28 - z) - y, x * y - 8 / 3 * z
        elif kind == "aizawa":
            dt = 0.01
            a, b, cc, d, e, f = 0.95, 0.7, 0.6, 3.5, 0.25, 0.1
            dx = (z - b) * x - d * y
            dy = d * x + (z - b) * y
            dz = cc + a * z - z**3 / 3 - (x * x + y * y) * (1 + e * z) + f * z * x**3
        else:  # thomas
            dt = 0.05
            b = 0.19
            dx, dy, dz = math.sin(y) - b * x, math.sin(z) - b * y, math.sin(x) - b * z
        x, y, z = x + dx * dt, y + dy * dt, z + dz * dt
        if i >= 400 and i % 3 == 0:  # skip the transient
            points.append((x, y, z))
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    cz = sum(p[2] for p in points) / len(points)
    extent = max(max(abs(p[0] - cx), abs(p[1] - cy), abs(p[2] - cz)) for p in points)
    scale = 2.3 / extent
    return [((p[0] - cx) * scale, (p[1] - cy) * scale, (p[2] - cz) * scale) for p in points]


def build(scene, params, ctx):
    c.reset(scene)
    primary, secondary, accent, deep = c.palette(params)
    points = _trace(params["kind"])
    verts, faces = c.tube(points, params["tube"], sides=8, closed=False)
    material = c.principled(
        "Trace", primary, metallic=0.3, roughness=0.35, emission=secondary, strength=0.4
    )
    trace = c.mesh_object(scene, "Attractor", verts, faces, material)
    trace.rotation_mode = "ZXY"
    c.drive(trace, "rotation_euler", c.phase(ctx["frames"]), 2)
    c.drive(
        trace, "rotation_euler", f"{math.radians(0 if params['kind'] == 'lorenz' else 20)!r}", 0
    )
    c.world(scene, c.mix(deep, (0, 0, 0, 1), 0.2), 0.5)
    c.light(scene, "AREA", (-4, -6, 5), (0, 0, 0), c.mix(accent, (1, 1, 1, 1), 0.5), 1400, 5)
    c.light(scene, "AREA", (5, 4, -1), (0, 0, 0), secondary, 900, 4, name="Rim")
    c.camera(scene, (0, -10.0, 0.5), (0, 0, 0), lens=38)
    return {"film_transparent": True}
