"""Endless flight over a procedural skyline; the city tile repeats every loop."""

import random

from presets import _common as c

TILE = 24.0
BLOCK = 2.0


def build(scene, params, ctx):
    c.reset(scene)
    primary, secondary, accent, deep = c.palette(params)
    rng = random.Random(params["seed"])
    frames = ctx["frames"]
    material = c.object_color_material("Building", roughness=0.6, emission=0.25)
    rows = int(TILE / BLOCK)
    footprint = []
    for j in range(rows):
        for i in range(-7, 8):
            if abs(i) <= 0 or rng.random() > params["density"]:
                continue  # keep the central avenue open
            h = rng.uniform(0.6, 1.0) ** 2 * (2.0 + 5.5 * min(1.0, abs(i) / 5))
            w = rng.uniform(0.9, 1.5)
            d = rng.uniform(0.9, 1.5)
            color = c.mix(primary, secondary, rng.random())
            if rng.random() < 0.12:
                color = accent
            footprint.append((i * BLOCK, j * BLOCK, w, d, h, color))
    # Three tiles: behind, current and ahead of the camera.
    for tile in range(-1, 5):
        for index, (x, y, w, d, h, color) in enumerate(footprint):
            building = c.box(
                scene, f"B{tile}_{index}", (w, d, h), material, (x, y + tile * TILE, 0), True
            )
            building.color = color
    ground = c.principled("Street", c.mix(deep, (0, 0, 0, 1), 0.6), roughness=0.9)
    c.box(scene, "Ground", (40, TILE * 7, 0.1), ground, (0, TILE * 2.5, -0.05))
    cam = c.camera(scene, (0, -8, 21), (0, 16, 0), lens=30)
    cam.data.clip_end = 300
    c.drive(cam, "location", c.loop_value(frames, TILE), 1)
    c.world(scene, c.mix(deep, (0, 0, 0, 1), 0.2), 0.4)
    c.light(scene, "SUN", (-3, -2, 6), (0, 0, 0), c.mix(accent, (1, 1, 1, 1), 0.6), 3.0)
    return {"film_transparent": True}
