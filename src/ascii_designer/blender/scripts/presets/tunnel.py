"""Endless flight through glowing tunnel segments.

All segments are identical up to a constant twist per segment. The camera moves
`travel` segments per loop and rolls by the accumulated twist, so the view at
frame N + 1 equals frame 1 exactly.
"""

import math

from presets import _common as c

SHAPES = {"ring": 0, "hex": 6, "square": 4}
SPACING = 2.2
RADIUS = 2.2


def build(scene, params, ctx):
    c.reset(scene)
    primary, secondary, accent, _deep = c.palette(params)
    sides = SHAPES[params["shape"]]
    travel = params["travel"]
    count = params["segments"] + travel + 3
    twist_loop = 2 * math.pi * params["twist"]  # camera roll per loop
    twist_step = twist_loop / travel  # rotation between neighbouring segments

    alternate = travel % 2 == 0
    fade = SPACING * params["segments"] * 0.35
    materials = [
        c.fading_emissive("SegmentA", primary, 8.0, fade),
        c.fading_emissive("SegmentB", secondary if alternate else primary, 8.0, fade),
    ]
    for k in range(count):
        y = (k - 1) * SPACING
        points = c.closed_polygon(sides, RADIUS, 16, rotation=k * twist_step + math.pi / 2)
        verts, faces = c.tube(points, 0.07, sides=12, closed=True)
        ring = c.mesh_object(scene, f"Segment{k:03d}", verts, faces, materials[k % 2])
        ring.location.y = y

    # Rails along the walls follow the twist, so they stay continuous.
    rails = 8 if sides == 0 else sides
    rail_mat = c.fading_emissive("Rail", c.mix(accent, (1, 1, 1, 1), 0.2), 3.0, fade)
    for j in range(rails):
        points = []
        for k in range(-1, count):
            a = k * twist_step + math.pi / 2 + 2 * math.pi * j / rails
            radius = RADIUS * (math.cos(math.pi / rails) if sides else 1.0) * 0.98
            points.append((radius * math.cos(a), (k - 1) * SPACING, radius * math.sin(a)))
        verts, faces = c.tube(points, 0.025, sides=8, closed=False)
        c.mesh_object(scene, f"Rail{j}", verts, faces, rail_mat)

    cam = c.camera(scene, (0.0, -SPACING, 0.0), (0.0, 10.0, 0.0), lens=24)
    cam.data.clip_end = 400.0
    cam.rotation_mode = "XYZ"
    c.drive(cam, "location", f"{-SPACING!r} + " + c.loop_value(ctx["frames"], travel * SPACING), 1)
    c.drive(cam, "rotation_euler", f"{math.pi / 2!r}", 0)
    c.drive(cam, "rotation_euler", c.loop_value(ctx["frames"], twist_loop), 1)
    c.world(scene, (0, 0, 0, 1), 0.0)
    # Distance fog via mist would break seams; depth falloff comes from the emissive rings.
    return {"film_transparent": True}
