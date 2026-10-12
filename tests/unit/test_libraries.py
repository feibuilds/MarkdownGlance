import importlib
import os
import sys
import tempfile
import unittest

from MarkdownGlance.preview import renderer
from MarkdownGlance.preview.renderer import markdown_engine

LISTS = "MarkdownGlance.preview.renderer.lists"


def _is_library(name):
    return name.split(".")[0] in ("markdown", "pymdownx") or name == LISTS


class LibraryFailureTest(unittest.TestCase):
    def stale_markdown(self):
        """Put a Markdown that cannot import ahead of the real one.

        This is the state Sublime Text 4213 and later start in after an
        upgrade: Python 3.14 runs the plugin, `Lib/python38` is still on
        `sys.path`, and the Markdown 3.2.2 in it fails on an `importlib`
        change. The directory here is `python33`, which no test run is.
        """
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        directory = os.path.join(root.name, "Lib", "python33")
        package = os.path.join(directory, "markdown")
        os.makedirs(package)
        with open(os.path.join(package, "__init__.py"), "w", encoding="utf-8") as out:
            out.write(
                "raise AttributeError(\"'EntryPoints' object has no attribute 'get'\")\n"
            )

        # `lists` subclasses the library's classes, so it goes with them.
        saved = {name: sys.modules.pop(name) for name in list(sys.modules) if _is_library(name)}
        engine = markdown_engine._default
        markdown_engine._default = None
        sys.path.insert(0, directory)
        importlib.invalidate_caches()

        def restore():
            if directory in sys.path:
                sys.path.remove(directory)
            for name in [name for name in sys.modules if _is_library(name)]:
                del sys.modules[name]
            sys.modules.update(saved)
            if LISTS in saved:
                renderer.lists = saved[LISTS]
            markdown_engine._default = engine
            importlib.invalidate_caches()

        self.addCleanup(restore)
        return package

    def test_working_libraries_are_no_failure(self):
        self.assertIsNone(markdown_engine.library_failure())
        self.assertEqual(
            sorted(markdown_engine.library_locations()),
            ["Markdown", "pymdown-extensions"],
        )

    def test_a_library_left_by_another_python_is_found_and_fails(self):
        package = self.stale_markdown()

        # Found, so the lookup at plugin load has nothing to say.
        self.assertEqual(markdown_engine.missing_libraries(), [])
        self.assertIsInstance(markdown_engine.library_failure(), AttributeError)
        location = markdown_engine.library_locations()["Markdown"]
        self.assertEqual(location, package)
        self.assertEqual(markdown_engine.other_python(location), "3.3")

    def test_the_failure_is_not_remembered(self):
        package = self.stale_markdown()
        self.assertIsNotNone(markdown_engine.library_failure())

        sys.path.remove(os.path.dirname(package))
        importlib.invalidate_caches()

        self.assertIsNone(markdown_engine.library_failure())

    def test_only_another_hosts_directory_is_another_python(self):
        own = "python{}{}".format(*sys.version_info[:2])
        self.assertEqual(
            markdown_engine.other_python(os.path.join("Data", "Lib", "python33", "markdown")),
            "3.3",
        )
        self.assertIsNone(
            markdown_engine.other_python(os.path.join("Data", "Lib", own, "markdown"))
        )
        # A virtual environment spells its directory with a dot.
        self.assertIsNone(
            markdown_engine.other_python(
                os.path.join("venv", "lib", "python3.3", "site-packages", "markdown")
            )
        )
