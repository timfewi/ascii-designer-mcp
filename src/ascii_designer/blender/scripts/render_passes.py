"""Render beauty + depth/normal passes for ascii-designer. Runs inside Blender 5.2.

Invoked as:
  blender -b --factory-startup -noaudio [-Y file.blend] --python-exit-code 1 \
      -P render_passes.py -- job.json

Outputs (in job["out_dir"]):
  beauty/NNNN.png  RGBA 8-bit, scene view transform, no dithering
  data/NNNN.exr    multilayer half-float EXR with raw Depth and Normal
Progress is reported as single JSON lines prefixed with "ASCII_DESIGNER ".
"""

import json
import sys
from pathlib import Path

import bpy

PREFIX = "ASCII_DESIGNER "
ENGINES = {"eevee": "BLENDER_EEVEE", "cycles": "CYCLES", "workbench": "BLENDER_WORKBENCH"}


def emit(event, **data):
    print(PREFIX + json.dumps({"event": event, **data}), flush=True)


def load_job():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if not argv:
        raise SystemExit("render_passes.py: missing job.json argument")
    return json.loads(Path(argv[0]).read_text(encoding="utf-8"))


def build_source(scene, job):
    source = job["source"]
    if source["kind"] != "preset":
        return {}
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import presets  # noqa: PLC0415 - only importable inside Blender

    context = {
        "frames": job["loop_frames"],
        "fps": job["fps"],
        "width": job["width"],
        "height": job["height"],
    }
    return presets.build(source["module"], scene, source["params"], context) or {}


def configure(scene, job, preset_info):
    render = scene.render
    render.resolution_x = job["width"]
    render.resolution_y = job["height"]
    render.resolution_percentage = 100
    render.pixel_aspect_x = render.pixel_aspect_y = 1.0
    if job.get("fps"):
        render.fps = job["fps"]
        render.fps_base = 1.0
    if job.get("frame_start") is not None:
        scene.frame_start = job["frame_start"]
        scene.frame_end = job["frame_end"]
    render.engine = ENGINES[job["engine"]]
    render.use_motion_blur = bool(job.get("motion_blur")) and job["engine"] != "workbench"
    render.motion_blur_shutter = 0.5
    render.dither_intensity = 0.0
    render.use_compositing = True
    render.use_sequencer = False
    if preset_info.get("film_transparent") is not None:
        render.film_transparent = bool(preset_info["film_transparent"])
    samples = int(job["samples"])
    if job["engine"] == "eevee":
        scene.eevee.taa_render_samples = samples
    elif job["engine"] == "cycles":
        scene.cycles.device = "CPU"
        scene.cycles.samples = samples
        scene.cycles.use_denoising = False
        scene.cycles.seed = 0
        scene.cycles.use_animated_seed = False
    if scene.camera is None:
        raise SystemExit("scene has no active camera")


def configure_outputs(scene, out_dir):
    render = scene.render
    settings = render.image_settings
    if hasattr(settings, "media_type"):
        settings.media_type = "IMAGE"
    settings.file_format = "PNG"
    settings.color_mode = "RGBA"
    settings.color_depth = "8"
    settings.compression = 15
    render.use_file_extension = True
    render.use_overwrite = True
    render.filepath = str(out_dir / "beauty") + "/"

    view_layer = scene.view_layers[0]
    view_layer.use_pass_z = True
    view_layer.use_pass_normal = True

    tree = bpy.data.node_groups.new("ascii_designer_passes", "CompositorNodeTree")
    scene.compositing_node_group = tree
    layers = tree.nodes.new("CompositorNodeRLayers")
    layers.scene = scene
    group_out = tree.nodes.new("NodeGroupOutput")
    tree.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    tree.links.new(layers.outputs["Image"], group_out.inputs["Image"])

    files = tree.nodes.new("CompositorNodeOutputFile")
    files.directory = str(out_dir / "data") + "/"
    files.file_name = ""
    fmt = files.format
    fmt.media_type = "MULTI_LAYER_IMAGE"
    fmt.file_format = "OPEN_EXR_MULTILAYER"
    fmt.color_depth = "16"
    fmt.exr_codec = "ZIP"
    linked = []
    for name, socket_type, source in (("depth", "FLOAT", "Depth"), ("normal", "VECTOR", "Normal")):
        output = layers.outputs.get(source)
        if output is None or not output.enabled:
            continue
        files.file_output_items.new(socket_type, name)
        tree.links.new(output, files.inputs[name])
        linked.append(name)
    return linked


def gpu_renderer():
    try:
        import gpu  # noqa: PLC0415

        return gpu.platform.renderer_get()
    except Exception:  # no GPU context in this session
        return "unknown"


def main():
    job = load_job()
    scene = bpy.context.scene
    if job["mode"] == "info":
        emit(
            "info",
            blender=bpy.app.version_string,
            file_version=list(bpy.data.version),
            frame_start=scene.frame_start,
            frame_end=scene.frame_end,
            fps=scene.render.fps / scene.render.fps_base,
            width=scene.render.resolution_x,
            height=scene.render.resolution_y,
            engine=scene.render.engine,
            camera=scene.camera is not None,
        )
        return
    preset_info = build_source(scene, job)
    configure(scene, job, preset_info)
    if job["mode"] == "save_blend":
        bpy.ops.wm.save_as_mainfile(filepath=job["blend_out"], copy=True)
        emit("saved", path=job["blend_out"])
        return

    out_dir = Path(job["out_dir"])
    (out_dir / "beauty").mkdir(parents=True, exist_ok=True)
    (out_dir / "data").mkdir(parents=True, exist_ok=True)
    passes = configure_outputs(scene, out_dir)
    if job.get("render_frames"):
        scene.frame_start, scene.frame_end = job["render_frames"]

    emit(
        "start",
        blender=bpy.app.version_string,
        engine=scene.render.engine,
        passes=passes,
        frame_start=scene.frame_start,
        frame_end=scene.frame_end,
        fps=scene.render.fps / scene.render.fps_base,
        view_transform=scene.view_settings.view_transform,
    )

    first = [True]

    def on_write(scene_, *_args):
        if first[0]:
            first[0] = False
            emit("renderer", renderer=gpu_renderer())
        emit("frame", frame=scene_.frame_current)

    bpy.app.handlers.render_write.append(on_write)
    bpy.ops.render.render(animation=True, scene=scene.name)
    emit("done", frame_start=scene.frame_start, frame_end=scene.frame_end)


main()
