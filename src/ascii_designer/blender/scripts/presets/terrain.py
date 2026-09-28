"""Synthwave flight over an endless mountain range.

The heightfield is periodic along the flight direction (integer wave numbers over
the tile length), and the camera moves exactly one tile per loop; the sun travels
with the camera. Frame N + 1 therefore equals frame 1.
"""

import math
import random

from presets import _common as c

TILE = 24.0
HALF_WIDTH = 22.0
AHEAD = 70.0


def _height_fn(seed, height):
    rng = random.Random(seed)
    waves = []
    for k in range(1, 9):
        waves.append(
            (
                1.0 / k**0.8,
                rng.randint(1, 3 + k),  # whole cycles per tile -> periodic in y
                rng.uniform(0.15, 0.9) * rng.choice((-1, 1)),
                rng.uniform(0, 2 * math.pi),
            )
        )
    total = sum(w[0] for w in waves)

    def height_at(x, y):
        n = sum(a * math.sin(2 * math.pi * m * y / TILE + b * x + p) for a, m, b, p in waves)
        n = 0.5 + 0.5 * n / total
        valley = min(1.0, max(0.0, (abs(x) - 2.5) / 7.0))
        valley = valley * valley * (3 - 2 * valley)
        return height * 5.0 * valley * n**1.6

    return height_at


def _grid(height_at, step):
    xs = [(-HALF_WIDTH + i * step) for i in range(int(2 * HALF_WIDTH / step) + 1)]
    ys = [(-4.0 + j * step) for j in range(int((TILE + AHEAD + 4) / step) + 1)]
    verts = [(x, y, height_at(x, y)) for y in ys for x in xs]
    width = len(xs)
    faces = [
        (j * width + i, j * width + i + 1, (j + 1) * width + i + 1, (j + 1) * width + i)
        for j in range(len(ys) - 1)
        for i in range(width - 1)
    ]
    return verts, faces


def _sun(scene, top, bottom, frames):
    import bmesh  # noqa: PLC0415 - Blender-only module

    radius, distance, elevation = 26.0, 150.0, 16.0
    bands = 9
    bm = bmesh.new()
    color_layer = bm.loops.layers.color.new("Col")
    for b in range(bands):
        z0 = radius - 2 * radius * b / bands
        z1 = z0 - 2 * radius / bands
        # Stripes widen towards the bottom, like the classic synthwave sun.
        gap = 0.0 if b < bands // 3 else (b - bands // 3 + 1) * 0.16 * (2 * radius / bands)
        lo, hi = z1 + gap, z0
        if hi <= lo:
            continue
        ring = []
        for z in (hi, lo):
            half = math.sqrt(max(radius * radius - z * z, 0.0))
            ring.append((-half, z))
            ring.append((half, z))
        verts = [
            bm.verts.new((ring[0][0], 0, ring[0][1])),
            bm.verts.new((ring[1][0], 0, ring[1][1])),
            bm.verts.new((ring[3][0], 0, ring[3][1])),
            bm.verts.new((ring[2][0], 0, ring[2][1])),
        ]
        face = bm.faces.new(verts)
        t = b / (bands - 1)
        for loop in face.loops:
            loop[color_layer] = c.mix(top, bottom, t)
    material = c.emissive("Sun", (1, 1, 1, 1), 4.0)
    nodes, links = material.node_tree.nodes, material.node_tree.links
    attribute = nodes.new("ShaderNodeVertexColor")
    attribute.layer_name = "Col"
    links.new(attribute.outputs["Color"], nodes["Principled BSDF"].inputs["Emission Color"])
    sun = c.bmesh_object(scene, "Sun", bm, material, smooth=False)
    sun.location = (0.0, distance, elevation)
    c.drive(sun, "location", f"{distance!r} + " + c.loop_value(frames, TILE), 1)
    return sun


def build(scene, params, ctx):
    c.reset(scene)
    primary, secondary, accent, deep = c.palette(params)
    frames = ctx["frames"]
    height_at = _height_fn(params["seed"], params["height"])
    wire = params["style"] == "wire"
    # TILE is a multiple of both steps, so the grid lines repeat every loop.
    verts, faces = _grid(height_at, 1.0 if wire else 0.5)
    fade = 22.0

    if wire:
        ground = c.principled("Ground", c.mix(deep, (0, 0, 0, 1), 0.7), roughness=0.9)
        c.mesh_object(scene, "Ground", verts, faces, ground, smooth=True)
        grid = c.mesh_object(
            scene, "Grid", verts, faces, c.fading_emissive("GridGlow", primary, 9.0, fade)
        )
        modifier = grid.modifiers.new("Wire", "WIREFRAME")
        modifier.thickness = 0.06
        modifier.use_replace = True
        grid.location.z = 0.01
    else:
        material = c.principled("Rock", primary, roughness=0.75)
        nodes, links = material.node_tree.nodes, material.node_tree.links
        geometry = nodes.new("ShaderNodeNewGeometry")
        separate = nodes.new("ShaderNodeSeparateXYZ")
        scale = nodes.new("ShaderNodeMapRange")
        scale.inputs["From Max"].default_value = 5.0 * params["height"]
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].color = c.mix(secondary, (0, 0, 0, 1), 0.6)
        ramp.color_ramp.elements[1].color = c.mix(primary, accent, 0.4)
        links.new(geometry.outputs["Position"], separate.inputs["Vector"])
        links.new(separate.outputs["Z"], scale.inputs["Value"])
        links.new(scale.outputs["Result"], ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], nodes["Principled BSDF"].inputs["Base Color"])
        c.mesh_object(scene, "Terrain", verts, faces, material, smooth=True)
        c.light(scene, "SUN", (0, 60, 12), (0, 0, 0), c.mix(accent, (1, 1, 1, 1), 0.5), 4.0)

    if params["sun"]:
        _sun(scene, accent, primary, frames)

    cam = c.camera(scene, (0.0, 0.0, 2.4), (0.0, 30.0, 1.2), lens=28)
    cam.data.clip_end = 400.0
    c.drive(cam, "location", c.loop_value(frames, TILE), 1)
    c.world(scene, (0, 0, 0, 1), 0.0)
    return {"film_transparent": True}
