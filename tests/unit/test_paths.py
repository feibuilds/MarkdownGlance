import ast
import ntpath
import os
import os.path
import pathlib
import posixpath
import unittest
from unittest import mock

from MarkdownGlance.preview.domain.contracts import (
    RenderRequest,
    RenderSettings,
    ThemeSnapshot,
)
from MarkdownGlance.preview.domain.paths import HOST, PathFlavour
from MarkdownGlance.preview.renderer import parse, structure

ROOT = pathlib.Path(__file__).parents[2] / "preview"
WINDOWS = PathFlavour(ntpath)
POSIX = PathFlavour(posixpath)
WINDOWS_HOME = {"USERPROFILE": "C:\\Users\\phil"}
POSIX_HOME = {"HOME": "/mdglance/home/phil"}


class PathFlavourTest(unittest.TestCase):
    def test_host_flavour_follows_the_interpreter_platform(self):
        self.assertIs(HOST.module, os.path)

    def test_relative_sources_join_with_native_separators(self):
        self.assertEqual(
            WINDOWS.resolve("C:\\docs", "images/a b.png"), "C:\\docs\\images\\a b.png"
        )
        self.assertEqual(
            POSIX.resolve("/mdglance/docs", "images/a b.png"),
            "/mdglance/docs/images/a b.png",
        )

    def test_parent_traversal_collapses_before_the_locator_is_used(self):
        self.assertEqual(
            WINDOWS.resolve("C:\\docs\\sub", "../images/a.png"),
            "C:\\docs\\images\\a.png",
        )
        self.assertEqual(
            POSIX.resolve("/mdglance/docs/sub", "../images/a.png"),
            "/mdglance/docs/images/a.png",
        )

    def test_rooted_source_keeps_the_windows_drive_but_replaces_a_posix_base(self):
        self.assertEqual(
            WINDOWS.resolve("C:\\docs", "/mdglance/secret"), "C:\\mdglance\\secret"
        )
        self.assertEqual(
            POSIX.resolve("/mdglance/docs", "/mdglance/secret"), "/mdglance/secret"
        )

    def test_tilde_expands_against_the_platform_home_before_the_base_join(self):
        with mock.patch.dict(os.environ, WINDOWS_HOME):
            self.assertEqual(
                WINDOWS.resolve("C:\\docs", "~/a.png"), "C:\\Users\\phil\\a.png"
            )
        with mock.patch.dict(os.environ, POSIX_HOME):
            self.assertEqual(
                POSIX.resolve("/mdglance/docs", "~/a.png"),
                "/mdglance/home/phil/a.png",
            )

    def test_an_expanded_tilde_reads_as_absolute_so_link_guards_reject_it(self):
        with mock.patch.dict(os.environ, WINDOWS_HOME):
            self.assertTrue(WINDOWS.is_absolute(WINDOWS.expand("~/a.png")))
        with mock.patch.dict(os.environ, POSIX_HOME):
            self.assertTrue(POSIX.is_absolute(POSIX.expand("~/a.png")))

    # Single-separator paths such as "\\a.png" are deliberately absent: ntpath
    # stopped calling them absolute in Python 3.13, so they answer differently
    # on the 3.8 and 3.14 legs of the matrix.
    def test_only_the_matching_flavour_finds_a_drive(self):
        self.assertEqual(WINDOWS.drive("C:\\docs\\a.png"), "C:")
        self.assertEqual(WINDOWS.drive("C:/docs/a.png"), "C:")
        self.assertEqual(POSIX.drive("C:/docs/a.png"), "")
        self.assertTrue(WINDOWS.is_drive_absolute("C:/docs/a.png"))
        self.assertFalse(POSIX.is_drive_absolute("C:/docs/a.png"))
        # Drive-relative, so not something to open beside the document.
        self.assertFalse(WINDOWS.is_drive_absolute("C:a.png"))
        self.assertFalse(WINDOWS.is_drive_absolute("images/a.png"))

    def test_a_unc_root_is_not_a_drive(self):
        # `splitdrive` hands back the whole share for one; reading it as a
        # local path would turn an image source into a network fetch.
        self.assertEqual(WINDOWS.drive("//host/share/a.png"), "")
        self.assertFalse(WINDOWS.is_drive_absolute("//host/share/a.png"))

    def test_a_file_url_path_drops_the_separator_before_a_drive(self):
        self.assertEqual(WINDOWS.from_url_path("/C:/docs/a.png"), "C:/docs/a.png")
        self.assertEqual(POSIX.from_url_path("/mdglance/docs/a.png"), "/mdglance/docs/a.png")
        self.assertEqual(WINDOWS.from_url_path("/docs/a.png"), "/docs/a.png")

    def test_only_the_matching_flavour_calls_a_locator_absolute(self):
        self.assertTrue(WINDOWS.is_absolute("C:\\docs\\a.png"))
        self.assertFalse(POSIX.is_absolute("C:\\docs\\a.png"))
        self.assertTrue(POSIX.is_absolute("/mdglance/docs/a.png"))
        self.assertFalse(WINDOWS.is_absolute("images/a.png"))
        self.assertFalse(POSIX.is_absolute("images/a.png"))


class RendererPathTest(unittest.TestCase):
    def keys(self, flavour, base_path, source="images/a%20b.png"):
        request = RenderRequest(
            "session",
            7,
            "![x]({})".format(source),
            base_path,
            1.0,
            RenderSettings(),
            ThemeSnapshot(),
            "opaque-token",
        )
        with mock.patch.object(structure, "HOST", flavour):
            return list(parse(request).asset_keys)

    def locator(self, flavour, base_path, source="images/a%20b.png"):
        return self.keys(flavour, base_path, source)[0].locator

    def test_local_image_locators_follow_the_host_flavour(self):
        self.assertEqual(self.locator(WINDOWS, "C:\\docs"), "C:\\docs\\images\\a b.png")
        self.assertEqual(
            self.locator(POSIX, "/mdglance/docs"), "/mdglance/docs/images/a b.png"
        )

    def test_tilde_image_sources_reach_the_home_directory(self):
        with mock.patch.dict(os.environ, WINDOWS_HOME):
            self.assertEqual(
                self.locator(WINDOWS, "C:\\docs", "~/a.png"),
                "C:\\Users\\phil\\a.png",
            )
        with mock.patch.dict(os.environ, POSIX_HOME):
            self.assertEqual(
                self.locator(POSIX, "/mdglance/docs", "~/a.png"),
                "/mdglance/home/phil/a.png",
            )

    def test_windows_absolute_sources_resolve_however_they_are_spelled(self):
        # `urlsplit` reads the drive letter as a scheme, and a `file:` URL
        # carries a separator in front of it; both used to end up unresolvable.
        for source in (
            "C:/docs/images/a b.png",
            "C:%5Cdocs%5Cimages%5Ca%20b.png",
            "file:///C:/docs/images/a%20b.png",
        ):
            self.assertEqual(
                self.locator(WINDOWS, "C:\\elsewhere", source),
                "C:\\docs\\images\\a b.png",
                source,
            )

    def test_a_posix_host_still_drops_a_drive_source(self):
        # Nothing changes off Windows: `C:/x.png` is not a path there, and the
        # scheme guard drops it as it always did.
        self.assertEqual(self.keys(POSIX, "/mdglance/docs", "C:/x.png"), [])

    def test_tilde_expands_even_without_a_base_path(self):
        with mock.patch.dict(os.environ, POSIX_HOME):
            self.assertEqual(
                self.locator(POSIX, None, "~/a.png"), "/mdglance/home/phil/a.png"
            )


class PathSeamTest(unittest.TestCase):
    GUARDED = frozenset(("expanduser", "isabs", "realpath", "splitdrive"))

    def test_platform_sensitive_calls_stay_inside_the_paths_module(self):
        for path in ROOT.rglob("*.py"):
            if path.name == "paths.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in self.GUARDED:
                    self.fail("{} calls {}".format(path, node.attr))
