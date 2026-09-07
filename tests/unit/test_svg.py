import io
import os
import shutil
import struct
import subprocess
import tempfile
import unittest

from MarkdownGlance.preview.assets.images import detect
from MarkdownGlance.preview.assets.svg import (
    SUPERSAMPLE,
    SvgRasteriser,
    SvgRenderFailed,
    intrinsic_size,
    zoom_for,
)
from MarkdownGlance.preview.domain.contracts import AssetStatus, RenderSettings

CIRCLE = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'
    b'<circle cx="10" cy="10" r="6" fill="#4f8cc9"/></svg>'
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", 80, 40) + b"\x00" * 8


class Completed:
    def __init__(self, returncode=0, stdout=PNG):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = b""


class Runner:
    """A stand-in for `subprocess.run` that records the command line."""

    def __init__(self, outcome=None):
        self.outcome = outcome or Completed()
        self.commands = []
        self.inputs = []

    def __call__(self, command, input=None, **kwargs):
        self.commands.append(command)
        self.inputs.append(input)
        self.kwargs = kwargs
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def rasteriser(outcome=None, backend="/usr/bin/resvg"):
    return SvgRasteriser(run=Runner(outcome), which=lambda name: backend)


class SizeTest(unittest.TestCase):
    def test_absolute_lengths_are_converted_to_pixels(self):
        self.assertEqual(intrinsic_size(CIRCLE), (40.0, 20.0))
        self.assertEqual(
            intrinsic_size(b'<svg width="1in" height="72pt" viewBox="0 0 9 9"/>'),
            (96.0, 96.0),
        )

    def test_percentages_and_missing_sizes_fall_back_to_the_view_box(self):
        for content in (
            b'<svg width="100%" height="100%" viewBox="0 0 30 10"/>',
            b'<svg viewBox="0,0,30,10"/>',
            b'<svg viewBox="0 0 30 10" width="1em"/>',
        ):
            self.assertEqual(intrinsic_size(content), (30.0, 10.0))

    def test_a_size_that_cannot_be_read_is_no_size_at_all(self):
        self.assertIsNone(intrinsic_size(b"<svg/>"))
        self.assertIsNone(intrinsic_size(b'<svg width="0" height="0"/>'))
        self.assertIsNone(intrinsic_size(b"<html><body>not an svg</body></html>"))

    def test_a_prologue_does_not_hide_the_root_element(self):
        prologued = (
            b'<?xml version="1.0"?>\n<!-- a drawing, width="9" in a comment -->\n'
            b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"/>'
        )
        self.assertEqual(intrinsic_size(prologued), (40.0, 20.0))

    def test_the_limit_caps_the_supersample_and_never_shrinks_below_one(self):
        self.assertEqual(zoom_for((40.0, 20.0), 4096), SUPERSAMPLE)
        self.assertEqual(zoom_for(None, 4096), SUPERSAMPLE)
        # 3000 px doubled would be over the limit, so it is drawn at the limit.
        self.assertEqual(zoom_for((3000.0, 100.0), 4096), 1.3653)
        self.assertEqual(zoom_for((3000.0, 100.0), 4096) * 3000.0 < 4096, True)
        # Already over it: drawn once, and reported as too large downstream.
        self.assertEqual(zoom_for((9000.0, 100.0), 4096), 1.0)


class RasteriseTest(unittest.TestCase):
    def test_the_command_reads_stdin_writes_stdout_and_carries_the_zoom(self):
        drawer = rasteriser()
        with tempfile.TemporaryDirectory() as base:
            png, scale = drawer.rasterise(CIRCLE, RenderSettings(), base)
        command = drawer._run.commands[0]
        self.assertEqual(png, PNG)
        self.assertEqual(scale, SUPERSAMPLE)
        self.assertEqual(command[0], "/usr/bin/resvg")
        self.assertEqual(command[-2:], ["-", "-c"])
        self.assertIn("--zoom", command)
        self.assertEqual(command[command.index("--zoom") + 1], "2.0000")
        self.assertEqual(command[command.index("--resources-dir") + 1], base)
        self.assertEqual(drawer._run.inputs[0], CIRCLE)
        self.assertEqual(drawer._run.kwargs["timeout"], 10.0)

    def test_a_drawing_from_the_network_gets_an_empty_resources_directory(self):
        drawer = rasteriser()
        drawer.rasterise(CIRCLE, RenderSettings())
        # A directory that does not exist is not passed through either: the
        # renderer would fall back to whatever it was started in.
        drawer.rasterise(CIRCLE, RenderSettings(), "/no/such/place")
        directories = [
            command[command.index("--resources-dir") + 1]
            for command in drawer._run.commands
        ]
        self.assertEqual(os.listdir(directories[0]), [])
        self.assertEqual(directories[0], directories[1])

    def test_a_timeout_a_crash_and_an_empty_image_are_one_failure(self):
        for outcome in (
            subprocess.TimeoutExpired("resvg", 10.0),
            OSError("no such file"),
            Completed(returncode=1, stdout=b""),
            Completed(returncode=0, stdout=b""),
        ):
            with self.assertRaises(SvgRenderFailed):
                rasteriser(outcome).rasterise(CIRCLE, RenderSettings())


class BackendTest(unittest.TestCase):
    def test_the_path_setting_names_an_executable_and_wins_over_the_path(self):
        with tempfile.TemporaryDirectory() as directory:
            configured = os.path.join(directory, "my-resvg")
            with open(configured, "wb") as handle:
                handle.write(b"#!/bin/sh\n")
            os.chmod(configured, 0o755)
            drawer = SvgRasteriser(run=Runner(), which=lambda name: "/usr/bin/resvg")
            settings = RenderSettings(svg_renderer_path=configured)
            self.assertEqual(drawer.backend(settings), configured)
            self.assertIsNone(drawer.unavailable(settings))
            missing = RenderSettings(
                svg_renderer_path=os.path.join(directory, "absent")
            )
            self.assertIsNone(drawer.backend(missing))
            self.assertEqual(
                drawer.unavailable(missing), AssetStatus.SVG_RENDERER_MISSING
            )

    def test_no_renderer_and_the_feature_off_are_different_answers(self):
        without = SvgRasteriser(run=Runner(), which=lambda name: None)
        self.assertEqual(
            without.unavailable(RenderSettings()), AssetStatus.SVG_RENDERER_MISSING
        )
        self.assertEqual(
            rasteriser().unavailable(RenderSettings(enable_svg=False)),
            AssetStatus.UNSUPPORTED_FORMAT,
        )


@unittest.skipUnless(shutil.which("resvg"), "resvg is not installed")
class InstalledRendererTest(unittest.TestCase):
    """The one test that runs the real thing, where there is one to run."""

    def test_a_drawing_comes_back_as_a_png_at_twice_its_size(self):
        png, scale = SvgRasteriser().rasterise(CIRCLE, RenderSettings())
        info = detect(io.BytesIO(png))
        self.assertEqual(scale, SUPERSAMPLE)
        self.assertEqual(
            (info.mime_type, info.width, info.height), ("image/png", 80, 40)
        )

    def test_a_malformed_drawing_fails_rather_than_hangs(self):
        with self.assertRaises(SvgRenderFailed):
            SvgRasteriser().rasterise(b"<svg", RenderSettings())


if __name__ == "__main__":
    unittest.main()
