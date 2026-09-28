"""Shared scene-building helpers for presets (Blender 5.2 API).

Animation uses drivers with simple expressions of `frame`, so presets loop
exactly (frame 1 == frame N + 1, including motion-blur subframes) and keep
working in .blend files opened with auto-run scripts disabled (-Y).
"""

import math

import bpy
from mathutils import Vector


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def color(hex_value, alpha=1.0):
    raw = hex_value.lstrip("#")
    r, g, b = (srgb_to_linear(int(raw[i : i + 2], 16) / 255) for i in (0, 2, 4))
    return (r, g, b, alpha)


def mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b, strict=True))


def palette(params):
    return [color(h) for h in params["palette_colors"]]


def reset(scene):
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for collection in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras):
        for block in list(collection):
            collection.remove(block)
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.eevee.use_raytracing = True


def world(scene, rgba, strength=1.0):
    world_ = scene.world or bpy.data.worlds.new("World")
    scene.world = world_
    world_.use_nodes = True
    background = world_.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = rgba
    background.inputs["Strength"].default_value = strength
    return world_


def link(obj, scene):
    scene.collection.objects.link(obj)
    return obj


def look_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def camera(scene, location, target=(0, 0, 0), lens=50.0):
    data = bpy.data.cameras.new("Camera")
    data.lens = lens
    data.clip_start = 0.05
    data.clip_end = 500.0
    obj = link(bpy.data.objects.new("Camera", data), scene)
    obj.location = location
    look_at(obj, target)
    scene.camera = obj
    return obj


def light(scene, kind, location, target, rgba, energy, size=1.0, name="Light"):
    data = bpy.data.lights.new(name, kind)
    data.color = rgba[:3]
    data.energy = energy
    if kind == "AREA":
        data.size = size
    elif kind in ("POINT", "SPOT"):
        data.shadow_soft_size = size
    obj = link(bpy.data.objects.new(name, data), scene)
    obj.location = location
    look_at(obj, target)
    return obj


def principled(name, base, metallic=0.0, roughness=0.5, emission=None, strength=0.0, coat=0.0):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    bsdf = material.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = base
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Coat Weight"].default_value = coat
    if emission is not None:
        bsdf.inputs["Emission Color"].default_value = emission
        bsdf.inputs["Emission Strength"].default_value = strength
    return material


def emissive(name, rgba, strength):
    return principled(name, (0, 0, 0, 1), roughness=1.0, emission=rgba, strength=strength)


def mesh_object(scene, name, verts, faces, material=None, smooth=True):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(v) for v in verts], [], faces)
    mesh.validate()
    if smooth:
        mesh.shade_smooth()
    if material is not None:
        mesh.materials.append(material)
    return link(bpy.data.objects.new(name, mesh), scene)


def drive(target, path, expression, index=-1):
    """Animate `target.path[index]` with a simple-expression driver of `frame`."""
    curve = target.driver_add(path, index) if index >= 0 else target.driver_add(path)
    curve.driver.type = "SCRIPTED"
    curve.driver.use_self = False
    curve.driver.expression = expression
    return curve


def phase(frames, turns=1.0):
    """Expression for the loop angle: 0 at frame 1, 2*pi*turns at frame N+1."""
    return f"(frame - 1) * {2 * math.pi * turns / frames!r}"


def loop_value(frames, amount):
    """Expression that grows linearly by `amount` per loop."""
    return f"(frame - 1) * {amount / frames!r}"


def tube(curve_points, radius, sides=24, closed=True):
    """Tube mesh around a polyline using parallel-transport frames (twist-free, seamless)."""
    n = len(curve_points)
    pts = [Vector(p) for p in curve_points]
    tangents = []
    for i in range(n):
        ahead, behind = ((i + 1) % n, i - 1) if closed else (min(i + 1, n - 1), max(i - 1, 0))
        t = pts[ahead] - pts[behind]
        tangents.append(t.normalized())
    helper = Vector((0, 0, 1)) if abs(tangents[0].z) < 0.9 else Vector((1, 0, 0))
    normal = tangents[0].cross(helper).normalized()
    normals = [normal]
    for i in range(1, n):
        axis, angle = _axis_angle(tangents[i - 1], tangents[i])
        normal = _rotate(normals[-1], axis, angle)
        normals.append((normal - tangents[i] * normal.dot(tangents[i])).normalized())
    if closed:
        end = _rotate(normals[-1], *_axis_angle(tangents[-1], tangents[0]))
        mismatch = _signed_angle(end, normals[0], tangents[0])
        normals = [_rotate(nv, tangents[i], -mismatch * i / n) for i, nv in enumerate(normals)]
    verts, faces = [], []
    for i in range(n):
        binormal = tangents[i].cross(normals[i])
        for k in range(sides):
            a = 2 * math.pi * k / sides
            verts.append(pts[i] + radius * (math.cos(a) * normals[i] + math.sin(a) * binormal))
    rings = n if closed else n - 1
    for i in range(rings):
        j = (i + 1) % n
        for k in range(sides):
            k2 = (k + 1) % sides
            faces.append((i * sides + k, j * sides + k, j * sides + k2, i * sides + k2))
    return verts, faces


def _axis_angle(a, b):
    axis = a.cross(b)
    if axis.length < 1e-9:
        return Vector((0, 0, 1)), 0.0
    return axis.normalized(), a.angle(b)


def _rotate(vector, axis, angle):
    from mathutils import Matrix  # noqa: PLC0415

    return Matrix.Rotation(angle, 3, axis) @ vector


def _signed_angle(a, b, axis):
    angle = a.angle(b)
    return angle if a.cross(b).dot(axis) >= 0 else -angle


def bmesh_object(scene, name, bm, material=None, smooth=True, location=(0, 0, 0)):
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    if smooth:
        mesh.shade_smooth()
    if material is not None:
        mesh.materials.append(material)
    obj = link(bpy.data.objects.new(name, mesh), scene)
    obj.location = location
    return obj


def uv_sphere(scene, name, radius, material=None, location=(0, 0, 0), segments=64, rings=32):
    import bmesh  # noqa: PLC0415 - Blender-only module

    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=rings, radius=radius)
    return bmesh_object(scene, name, bm, material, True, location)


def box(scene, name, size, material=None, location=(0, 0, 0), base_origin=False):
    """Axis-aligned box; with base_origin the origin sits on the bottom face."""
    import bmesh  # noqa: PLC0415

    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x *= size[0]
        v.co.y *= size[1]
        v.co.z = (v.co.z + 0.5) * size[2] if base_origin else v.co.z * size[2]
    return bmesh_object(scene, name, bm, material, False, location)


def object_color_material(name, metallic=0.0, roughness=0.45, emission=0.0):
    """Principled material whose colour comes from each object's `color` property."""
    material = principled(name, (1, 1, 1, 1), metallic=metallic, roughness=roughness)
    nodes, links = material.node_tree.nodes, material.node_tree.links
    info = nodes.new("ShaderNodeObjectInfo")
    bsdf = nodes["Principled BSDF"]
    links.new(info.outputs["Color"], bsdf.inputs["Base Color"])
    if emission > 0:
        links.new(info.outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = emission
    return material


def ortho_camera(scene, location, target, scale):
    cam = camera(scene, location, target)
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = scale
    return cam


def closed_polygon(sides, radius, samples_per_side=24, rotation=0.0):
    """Points along a regular polygon (sides >= 3) or circle (sides == 0), in the XZ plane."""
    points = []
    if sides == 0:
        total = samples_per_side * 8
        for i in range(total):
            a = rotation + 2 * math.pi * i / total
            points.append((radius * math.cos(a), 0.0, radius * math.sin(a)))
        return points
    corners = [
        (
            radius * math.cos(rotation + 2 * math.pi * k / sides),
            radius * math.sin(rotation + 2 * math.pi * k / sides),
        )
        for k in range(sides)
    ]
    for k in range(sides):
        (x0, z0), (x1, z1) = corners[k], corners[(k + 1) % sides]
        for j in range(samples_per_side):
            t = j / samples_per_side
            points.append((x0 + (x1 - x0) * t, 0.0, z0 + (z1 - z0) * t))
    return points


def fading_emissive(name, rgba, strength, falloff):
    """Emission that fades with view distance (exp(-d / falloff)); loop-safe depth cue."""
    material = emissive(name, rgba, strength)
    nodes, links = material.node_tree.nodes, material.node_tree.links
    bsdf = nodes["Principled BSDF"]
    camera_data = nodes.new("ShaderNodeCameraData")
    scale = nodes.new("ShaderNodeMath")
    scale.operation = "MULTIPLY"
    scale.inputs[1].default_value = -1.0 / falloff
    exp = nodes.new("ShaderNodeMath")
    exp.operation = "EXPONENT"
    gain = nodes.new("ShaderNodeMath")
    gain.operation = "MULTIPLY"
    gain.inputs[1].default_value = strength
    links.new(camera_data.outputs["View Distance"], scale.inputs[0])
    links.new(scale.outputs[0], exp.inputs[0])
    links.new(exp.outputs[0], gain.inputs[0])
    links.new(gain.outputs[0], bsdf.inputs["Emission Strength"])
    return material
