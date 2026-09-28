"""Procedural preset scenes. Runs inside Blender; see ascii_designer.presets for the catalog."""

import importlib


def build(module, scene, params, context):
    """Build the preset into `scene`; returns render hints such as film_transparent."""
    return importlib.import_module(f"presets.{module}").build(scene, params, context)
