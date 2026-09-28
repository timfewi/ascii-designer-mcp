"""Rotating planet with noise continents, ring system, fresnel atmosphere and stars.

The surface texture lives in object space, so a whole number of rotations per
loop is seamless; moons orbit a whole number of times as well.
"""

import math
import random

from mathutils import Matrix

from presets import _common as c


def _surface(primary, secondary, accent, seed):
    material = c.principled("Surface", secondary, roughness=0.8)
    nodes, links = material.node_tree.nodes, material.node_tree.links
    bsdf = nodes["Principled BSDF"]
    coords = nodes.new("ShaderNodeTexCoord")
    noise = nodes.new("ShaderNodeTexNoise")
    noise.noise_dimensions = "4D"
    noise.inputs["W"].default_value = seed * 0.37
    noise.inputs["Scale"].default_value = 2.1
    noise.inputs["Detail"].default_value = 6.0
    noise.inputs["Roughness"].default_value = 0.55
    ramp = nodes.new("ShaderNodeValToRGB")
    elements = ramp.color_ramp.elements
    elements[0].position, elements[0].color = 0.5, c.mix(secondary, (0, 0, 0, 1), 0.88)
    elements[1].position, elements[1].color = 0.53, primary
    peak = elements.new(0.68)
    peak.color = c.mix(accent, (1, 1, 1, 1), 0.35)
    links.new(coords.outputs["Object"], noise.inputs["Vector"])
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.25
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return material


def _atmosphere(color):
    material = c.principled("Atmosphere", (0, 0, 0, 1), roughness=1.0)
    material.surface_render_method = "BLENDED"
    nodes, links = material.node_tree.nodes, material.node_tree.links
    out = nodes["Material Output"]
    weight = nodes.new("ShaderNodeLayerWeight")
    weight.inputs["Blend"].default_value = 0.12
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = color
    emission.inputs["Strength"].default_value = 1.6
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    mix = nodes.new("ShaderNodeMixShader")
    links.new(weight.outputs["Facing"], mix.inputs["Fac"])
    links.new(transparent.outputs["BSDF"], mix.inputs[1])
    links.new(emission.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return material


def _rings(scene, color):
    import bmesh  # noqa: PLC0415 - Blender-only module

    bm = bmesh.new()
    bands = [(1.5, 1.72, 0.9), (1.78, 2.1, 1.0), (2.2, 2.45, 0.75)]
    segments = 256
    for inner, outer, _level in bands:
        rim = []
        for radius in (inner, outer):
            rim.append(
                [
                    bm.verts.new(
                        (
                            radius * math.cos(2 * math.pi * i / segments),
                            radius * math.sin(2 * math.pi * i / segments),
                            0.0,
                        )
                    )
                    for i in range(segments)
                ]
            )
        for i in range(segments):
            j = (i + 1) % segments
            bm.faces.new((rim[0][i], rim[0][j], rim[1][j], rim[1][i]))
    material = c.principled("Rings", color, roughness=0.7)
    rings = c.bmesh_object(scene, "Rings", bm, material, smooth=False)
    rings.rotation_euler = (math.radians(14), math.radians(-16), 0.0)
    return rings


def _stars(scene, seed, count=260):
    import bmesh  # noqa: PLC0415

    rng = random.Random(seed)
    bm = bmesh.new()
    for _ in range(count):
        # A shell behind the planet; varied sizes so some stars fill whole cells.
        theta = rng.uniform(-0.55, 0.55)
        phi = rng.uniform(-0.9, 0.9)
        distance = rng.uniform(40, 60)
        x = distance * math.sin(phi)
        z = distance * math.sin(theta)
        y = distance * math.cos(phi)
        size = rng.choice((0.04, 0.06, 0.08, 0.1, 0.13))
        bmesh.ops.create_icosphere(
            bm,
            subdivisions=1,
            radius=size,
            matrix=Matrix.Translation((x, y, z)),
        )
    material = c.emissive("Stars", (1, 1, 1, 1), 6.0)
    return c.bmesh_object(scene, "Stars", bm, material, smooth=False)


def build(scene, params, ctx):
    c.reset(scene)
    primary, secondary, accent, deep = c.palette(params)
    frames = ctx["frames"]

    planet = c.uv_sphere(scene, "Planet", 1.0, _surface(primary, secondary, accent, params["seed"]))
    planet.rotation_mode = "ZXY"
    c.drive(planet, "rotation_euler", c.phase(frames, params["turns"]), 2)
    c.drive(planet, "rotation_euler", f"{math.radians(18)!r}", 1)
    c.uv_sphere(scene, "Atmosphere", 1.07, _atmosphere(c.mix(secondary, (1, 1, 1, 1), 0.3)))
    if params["rings"]:
        _rings(scene, c.mix(accent, primary, 0.35))

    moon_mat = c.principled("Moon", c.mix(accent, (0.7, 0.7, 0.7, 1), 0.6), roughness=0.9)
    for m in range(params["moons"]):
        moon = c.uv_sphere(scene, f"Moon{m}", 0.09 + 0.04 * m, moon_mat, segments=32, rings=16)
        radius = 2.9 + 0.7 * m
        angle = f"{c.phase(frames, 1 + m)} + {m * 2.1!r}"
        c.drive(moon, "location", f"{radius!r} * cos({angle})", 0)
        c.drive(moon, "location", f"{radius!r} * sin({angle})", 1)
        c.drive(moon, "location", f"{0.35 * radius!r} * sin({angle})", 2)

    _stars(scene, params["seed"])
    c.world(scene, c.mix(deep, (0, 0, 0, 1), 0.5), strength=0.15)
    c.light(scene, "SUN", (7, -2.5, 2.5), (0, 0, 0), c.mix(accent, (1, 1, 1, 1), 0.7), 5.0)
    c.light(scene, "AREA", (-5, -3, -1), (0, 0, 0), secondary, 60, 4, name="Bounce")
    c.camera(scene, (0.0, -8.4, 1.3), (0.0, 0.0, -0.1), lens=40)
    return {"film_transparent": True}
