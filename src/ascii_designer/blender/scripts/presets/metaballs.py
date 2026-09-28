"""Liquid metaballs orbiting on periodic Lissajous paths and merging."""

import math
import random

import bpy

from presets import _common as c


def build(scene, params, ctx):
    c.reset(scene)
    primary, secondary, accent, deep = c.palette(params)
    rng = random.Random(params["seed"])
    frames = ctx["frames"]
    data = bpy.data.metaballs.new("Blob")
    data.resolution = 0.06
    data.render_resolution = 0.05
    data.threshold = 0.6
    blob = c.link(bpy.data.objects.new("Blob", data), scene)
    material = c.principled("Liquid", primary, metallic=0.9, roughness=0.12, coat=0.8)
    data.materials.append(material)
    for k in range(params["balls"]):
        element = data.elements.new()
        element.radius = rng.uniform(1.0, 1.45)
        # Whole frequencies keep every path periodic over one loop.
        fx, fy, fz = rng.randint(1, 2), rng.randint(1, 3), rng.randint(1, 2)
        px, py, pz = (rng.uniform(0, 2 * math.pi) for _ in range(3))
        ax, ay, az = rng.uniform(0.8, 1.4), rng.uniform(0.4, 0.9), rng.uniform(0.5, 1.0)
        phase = c.phase(frames)
        for axis, (amp, freq, off) in enumerate(((ax, fx, px), (ay, fy, py), (az, fz, pz))):
            c.drive(data, f"elements[{k}].co", f"{amp!r} * sin({freq} * {phase} + {off!r})", axis)
    c.world(scene, c.mix(deep, secondary, 0.25), 1.0)
    c.light(scene, "AREA", (-4, -5, 5), (0, 0, 0), (1, 1, 1, 1), 1500, 4)
    c.light(scene, "AREA", (5, 3, 1), (0, 0, 0), secondary, 1400, 4, name="Rim")
    c.light(scene, "AREA", (0, 2, -5), (0, 0, 0), accent, 600, 5, name="Under")
    c.camera(scene, (0, -7.2, 1.0), (0, 0, 0), lens=40)
    del blob
    return {"film_transparent": True}
