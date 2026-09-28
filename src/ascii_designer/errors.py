"""Error types shared by the CLI and the MCP server."""


class DesignerError(Exception):
    """A user-facing failure with an actionable message."""


class SpecError(DesignerError):
    """The job specification is invalid."""


class EnvironmentBlockedError(DesignerError):
    """A required external tool (blender, ffmpeg, font) is missing or unusable."""


class RenderError(DesignerError):
    """An external renderer or encoder failed."""
