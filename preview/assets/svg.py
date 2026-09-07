import atexit
import math
import os
import re
import shutil
import subprocess
import tempfile
from typing import Callable, Optional, Tuple

from ..domain.contracts import AssetStatus, RenderSettings
from ..domain.paths import HOST

# minihtml decodes PNG, JPEG and GIF and nothing else, so an SVG reaches the
# preview as a PNG a renderer drew here on this machine: no upload, no account,
# and the document's own image reference is left alone (ADR 0019). resvg is
# that renderer -- a single static binary, no Cairo underneath it, and a subset
# aimed at static SVG rather than a browser engine.
RENDERER = "resvg"

# The PNG is drawn at twice the size it is shown at and scaled down by the
# serialiser, so that a diagram's text is as crisp as the text beside it on a
# high-DPI display and survives a zoom step or two. Two is also the factor a
# formula is fetched at (ADR 0013); the cost is four times the pixels, which
# `remote_max_dimension` still bounds.
SUPERSAMPLE = 2.0

# How far in to look for the root element. The prologue an SVG may carry --
# BOM, XML declaration, comments, DOCTYPE with an internal subset -- is what
# makes this more than a couple of hundred bytes.
HEADER_BYTES = 8192

# CSS absolute units, in the 96 dpi pixels resvg renders at. A relative unit
# (`em`, `ex`, `%`) depends on a context an image has no business assuming, so
# it is left to the `viewBox` below.
_UNITS = {
    "": 1.0,
    "px": 1.0,
    "pt": 96.0 / 72.0,
    "pc": 16.0,
    "mm": 96.0 / 25.4,
    "cm": 96.0 / 2.54,
    "in": 96.0,
}

_ROOT = re.compile(r"<svg\b((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>", re.IGNORECASE)
_ATTRIBUTE = re.compile(r"([\w:.-]+)\s*=\s*(\"[^\"]*\"|'[^']*')")
_LENGTH = re.compile(r"^([+-]?[0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)([a-z%]*)$")


class SvgRenderFailed(Exception):
    """The renderer was there and did not produce a PNG.

    A malformed file, a feature the renderer does not implement, a crash, or a
    run that outlived its timeout: all of them are one thing to the reader,
    who is told the image could not be drawn and that Open in Browser can.
    """


def _length(value: str) -> Optional[float]:
    match = _LENGTH.match(value.strip().lower())
    if match is None:
        return None
    factor = _UNITS.get(match.group(2))
    if factor is None:
        return None
    size = float(match.group(1)) * factor
    return size if size > 0 else None


def intrinsic_size(content: bytes) -> Optional[Tuple[float, float]]:
    """The size the root element asks to be drawn at, in CSS pixels.

    `width` and `height` when both are absolute lengths, the `viewBox` when
    they are missing or given as percentages -- which is what resvg itself
    falls back to. `None` when neither is readable, and then nothing is known
    about the image until it has been drawn.
    """
    header = content[:HEADER_BYTES].decode("latin-1")
    root = _ROOT.search(header)
    if root is None:
        return None
    attributes = {
        name.lower(): value[1:-1] for name, value in _ATTRIBUTE.findall(root.group(1))
    }
    width = _length(attributes.get("width", ""))
    height = _length(attributes.get("height", ""))
    if width is not None and height is not None:
        return (width, height)
    box = attributes.get("viewbox", "").replace(",", " ").split()
    if len(box) == 4:
        try:
            box_width, box_height = float(box[2]), float(box[3])
        except ValueError:
            return None
        if box_width > 0 and box_height > 0:
            return (width or box_width, height or box_height)
    return None


def zoom_for(size: Optional[Tuple[float, float]], max_dimension: int) -> float:
    """The factor to draw at: the supersample, less whatever the limit takes.

    Rounded down to the precision the command line carries, so that an image
    whose intrinsic size is already at the limit comes back at the limit
    rather than a pixel over it and reported as too large.
    """
    zoom = SUPERSAMPLE
    if size is not None and max(size) > 0:
        zoom = max(1.0, min(SUPERSAMPLE, max_dimension / max(size)))
    return math.floor(zoom * 10000.0) / 10000.0


def _hidden_window():
    """Keep a console window from flashing on Windows for every image."""
    if os.name != "nt":
        return {}
    return {"creationflags": 0x08000000}  # CREATE_NO_WINDOW


class SvgRasteriser:
    """Draws an SVG as a PNG by running the renderer as a child process.

    Out of process on purpose: `subprocess.run(..., timeout=...)` kills a run
    that will not finish, which no in-process native renderer would let us do,
    and a renderer that segfaults on a malformed file takes a child down
    rather than Sublime Text.
    """

    def __init__(
        self,
        run: Optional[Callable[..., subprocess.CompletedProcess]] = None,
        which: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        self._run = run or subprocess.run
        self._which = which or shutil.which
        self._empty_dir = None  # type: Optional[str]

    def backend(self, settings: RenderSettings) -> Optional[str]:
        """The renderer to run: the configured one, or `resvg` on the PATH.

        The setting names an executable, never a command line, and the
        arguments are this module's own; a settings file cannot turn it into
        an arbitrary command.
        """
        configured = settings.svg_renderer_path.strip()
        if configured:
            path = HOST.expand(configured)
            return path if os.access(path, os.X_OK) and os.path.isfile(path) else None
        return self._which(RENDERER)

    def unavailable(self, settings: RenderSettings) -> Optional[AssetStatus]:
        """Why an SVG cannot be drawn at all, or `None` when it can be.

        Asked before the work is handed to a thread, so that the two answers
        that need no renderer -- the feature is off, or none is installed --
        cost nothing and are reported straight away.
        """
        if not settings.enable_svg:
            return AssetStatus.UNSUPPORTED_FORMAT
        if self.backend(settings) is None:
            return AssetStatus.SVG_RENDERER_MISSING
        return None

    def _resources_dir(self, base_dir: Optional[str]) -> str:
        """Where the renderer resolves an `<image href>` inside the drawing.

        A local SVG gets the directory it sits in, so a diagram that points at
        a sibling PNG draws the same as it does in a browser. Anything else --
        a badge, a diagram off the network -- gets an empty directory of our
        own, so that a relative reference in a file from elsewhere reaches
        nothing on this machine. Left unset, the renderer would resolve
        against whatever directory Sublime Text was started in.
        """
        if base_dir and os.path.isdir(base_dir):
            return base_dir
        if self._empty_dir is None:
            self._empty_dir = tempfile.mkdtemp(prefix="mdglance-svg-")
            atexit.register(_forget_dir, self._empty_dir)
        return self._empty_dir

    def rasterise(
        self,
        content: bytes,
        settings: RenderSettings,
        base_dir: Optional[str] = None,
    ) -> Tuple[bytes, float]:
        """The PNG bytes, and the factor they were drawn at."""
        backend = self.backend(settings)
        if backend is None:
            raise SvgRenderFailed("no SVG renderer")
        zoom = zoom_for(intrinsic_size(content), settings.remote_max_dimension)
        command = [
            backend,
            "--quiet",
            "--resources-dir",
            self._resources_dir(base_dir),
            "--zoom",
            "{:.4f}".format(zoom),
            "-",
            "-c",
        ]
        try:
            completed = self._run(
                command,
                input=content,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=settings.svg_timeout_seconds,
                **_hidden_window()
            )
        except subprocess.TimeoutExpired:
            raise SvgRenderFailed("renderer timed out")
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise SvgRenderFailed(str(error))
        if completed.returncode != 0 or not completed.stdout:
            raise SvgRenderFailed("renderer wrote no image")
        return completed.stdout, zoom


def _forget_dir(path: str) -> None:
    try:
        os.rmdir(path)
    except OSError:
        pass
