"""A logo image as an embossed, double-sided 3D emblem.

The image is sampled on a grid: the foreground mask (alpha, or distance from
the border colour for opaque images) sets where the emblem exists, and the
brightness of each colour region sets how far it stands out (`relief`). Front
and back are mirrored like a coin, so it can also spin. The original colours
are applied as a texture; all motion is periodic over one loop.
"""

import bpy
import numpy as np

from presets import _common as c

SIZE = 4.0  # long side of the emblem in scene units


def _load(path):
    image = bpy.data.images.load(path, check_existing=True)
    width, height = image.size
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    return image, pixels.reshape(height, width, 4)  # rows run bottom to top


def _downsample(rgba, samples):
    height, width = rgba.shape[:2]
    scale = samples / max(width, height)
    gw, gh = max(2, round(width * scale)), max(2, round(height * scale))
    ys = (np.arange(gh + 1) * height // gh).astype(np.int64)
    xs = (np.arange(gw + 1) * width // gw).astype(np.int64)
    rows = np.add.reduceat(rgba, ys[:-1], axis=0) / np.diff(ys)[:, None, None]
    return np.add.reduceat(rows, xs[:-1], axis=1) / np.diff(xs)[None, :, None]


def _mask(rgba):
    alpha = rgba[..., 3]
    if float(alpha.min()) < 0.5:  # the image carries real transparency
        return np.clip((alpha - 0.15) / 0.5, 0.0, 1.0)
    border = np.concatenate(
        [rgba[0, :, :3], rgba[-1, :, :3], rgba[:, 0, :3], rgba[:, -1, :3]], axis=0
    )
    background = np.median(border, axis=0)
    distance = np.linalg.norm(rgba[..., :3] - background, axis=-1)
    return np.clip((distance - 0.08) / 0.15, 0.0, 1.0)


def _heights(rgba, mask, thickness, relief):
    lum = rgba[..., :3] @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    solid = mask > 0.5
    if solid.any():
        lo, hi = np.percentile(lum[solid], (5, 95))
    else:
        lo, hi = 0.0, 1.0
    rank = np.clip((lum - lo) / max(hi - lo, 1e-3), 0.0, 1.0)
    return thickness * mask * (1.0 - relief + relief * rank)


def _emblem_mesh(scene, rgba, mask, heights, material):
    gh, gw = mask.shape
    unit = SIZE / (max(gw, gh) - 1)
    corner_max = np.maximum.reduce([mask[:-1, :-1], mask[:-1, 1:], mask[1:, :-1], mask[1:, 1:]])
    keep_j, keep_i = np.nonzero(corner_max > 0.05)
    quads = np.stack(
        [
            keep_j * gw + keep_i,
            keep_j * gw + keep_i + 1,
            (keep_j + 1) * gw + keep_i + 1,
            (keep_j + 1) * gw + keep_i,
        ],
        axis=1,
    )
    used = np.unique(quads)
    remap = np.full(gh * gw, -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    j, i = np.divmod(used, gw)
    x = (i - (gw - 1) / 2) * unit
    z = (j - (gh - 1) / 2) * unit
    h = heights[j, i]
    count = len(used)
    front = np.stack([x, -h, z], axis=1)  # the camera looks along +Y
    back = np.stack([x, h, z], axis=1)
    verts = np.concatenate([front, back]).astype(np.float64)
    faces_front = remap[quads]
    faces_back = faces_front[:, ::-1] + count
    faces = np.concatenate([faces_front, faces_back])

    mesh = bpy.data.meshes.new("Emblem")
    mesh.from_pydata(verts.tolist(), [], faces.tolist())
    grid_uv = np.stack([(i + 0.5) / gw, (j + 0.5) / gh], axis=1)
    all_uv = np.concatenate([grid_uv, grid_uv])
    layer = mesh.uv_layers.new(name="UVMap")
    layer.data.foreach_set("uv", all_uv[faces.ravel()].astype(np.float32).ravel())
    mesh.validate()
    mesh.materials.append(material)
    return c.link(bpy.data.objects.new("Emblem", mesh), scene)


def _material(image, look, accent):
    if look == "neon":
        material = c.principled("Logo", (0.02, 0.02, 0.02, 1), roughness=0.5)
    elif look == "metal":
        material = c.principled("Logo", (1, 1, 1, 1), metallic=0.85, roughness=0.3)
    elif look == "matte":
        material = c.principled("Logo", (1, 1, 1, 1), roughness=0.7)
    else:
        material = c.principled("Logo", (1, 1, 1, 1), roughness=0.28, coat=0.6)
    nodes, links = material.node_tree.nodes, material.node_tree.links
    bsdf = nodes["Principled BSDF"]
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = image
    texture.interpolation = "Linear"
    texture.extension = "EXTEND"
    if look == "neon":
        links.new(texture.outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = 3.0
    else:
        links.new(texture.outputs["Color"], bsdf.inputs["Base Color"])
        bsdf.inputs["Emission Color"].default_value = accent
        bsdf.inputs["Emission Strength"].default_value = 0.0
    return material


def build(scene, params, ctx):
    c.reset(scene)
    primary, secondary, accent, deep = c.palette(params)
    frames = ctx["frames"]
    image, rgba = _load(params["image"])
    grid = _downsample(rgba, params["resolution"])
    mask = _mask(grid)
    heights = _heights(grid, mask, params["thickness"], params["relief"])
    emblem = _emblem_mesh(scene, grid, mask, heights, _material(image, params["material"], accent))

    phase = c.phase(frames)
    emblem.rotation_mode = "XYZ"
    motion = params["motion"]
    if motion == "spin":
        c.drive(emblem, "rotation_euler", c.phase(frames, params["turns"]), 2)
        c.drive(emblem, "rotation_euler", f"0.08 * sin({phase})", 0)
    elif motion == "float":
        c.drive(emblem, "rotation_euler", f"0.32 * sin({phase})", 2)
        c.drive(emblem, "rotation_euler", f"0.10 * sin(2 * {phase})", 0)
        c.drive(emblem, "location", f"0.12 * sin(2 * {phase})", 2)
    else:  # sway
        c.drive(emblem, "rotation_euler", f"0.55 * sin({phase})", 2)
        c.drive(emblem, "rotation_euler", f"0.09 * cos({phase})", 0)

    gh, gw = mask.shape
    width_units = SIZE * gw / max(gw, gh)
    height_units = SIZE * gh / max(gw, gh)
    aspect = ctx["height"] / ctx["width"]
    tan_h = 18.0 / 50.0  # 36 mm sensor, 50 mm lens
    tan_v = tan_h * aspect
    distance = max(0.5 * height_units * 1.28 / tan_v, 0.5 * width_units * 1.35 / tan_h)
    c.camera(scene, (0.0, -distance, 0.0), (0, 0, 0), lens=50)

    c.world(scene, c.mix(deep, (0, 0, 0, 1), 0.4), 0.5)
    c.light(scene, "AREA", (-3.5, -6.0, 4.0), (0, 0, 0), (1, 1, 1, 1), 1100, 5, name="Key")
    c.light(
        scene,
        "AREA",
        (5.0, 3.0, 2.5),
        (0, 0, 0),
        c.mix(primary, (1, 1, 1, 1), 0.3),
        900,
        3,
        name="RimR",
    )
    c.light(
        scene,
        "AREA",
        (-5.0, 3.0, -2.0),
        (0, 0, 0),
        c.mix(secondary, (1, 1, 1, 1), 0.3),
        700,
        3,
        name="RimL",
    )
    c.light(scene, "AREA", (0.0, -5.0, -3.5), (0, 0, 0), (1, 1, 1, 1), 250, 6, name="Fill")
    return {"film_transparent": True}
