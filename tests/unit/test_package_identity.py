import ast
import copy
import json
import os
import re
import unittest

from MarkdownGlance.preview.domain.contracts import RenderSettings

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
BINDINGS = ("sublime-keymap", "sublime-mousemap")
PLATFORMS = ("Linux", "OSX", "Windows")
# Sublime names the "=" and "-" keys on macOS; the literal characters Linux and
# Windows accept never match there, so the OSX keymap must spell them out.
MACOS_KEY_NAMES = {"=": "equals", "-": "minus"}
# ADR 0009: the Full Screen toggle deliberately shadows paste_and_indent, and
# ADR 0010: the panel toggle shadows Build With…, both only while a Markdown
# source view is focused. ADR 0016: the two zoom keys shadow Sublime's own font
# size, and only while a Markdown source is focused *and* the window has a
# preview -- `ctrl+0` is deliberately not among them, because Sublime has no
# other binding for `focus_side_bar`. Nothing else may cost the user a key.
SINGLE_STROKE_OUTSIDE_PREVIEW = frozenset(
    {
        "ctrl+shift+v",
        "super+shift+v",
        "ctrl+shift+b",
        "super+shift+b",
        "ctrl+=",
        "super+equals",
        "ctrl+-",
        "super+minus",
    }
)
# Contexts that are true only inside a view this package created.
OWN_SURFACE_CONTEXTS = frozenset(
    {"mdglance.preview_focused", "mdglance.panel_focused"}
)


def as_macos_key(key):
    prefix, plus, last = key.replace("ctrl+", "super+").rpartition("+")
    return prefix + plus + MACOS_KEY_NAMES.get(last, last)


def as_macos(bindings):
    macos = copy.deepcopy(bindings)
    for item in macos:
        item["keys"] = [as_macos_key(key) for key in item.get("keys", ())]
        item["modifiers"] = [
            modifier.replace("ctrl", "super") for modifier in item.get("modifiers", ())
        ]
        for name in ("keys", "modifiers"):
            if not item[name]:
                del item[name]
    return macos


class PackageIdentityTest(unittest.TestCase):
    def load(self, name):
        with open(os.path.join(ROOT, name), encoding="utf-8") as source:
            return json.load(source)

    def test_metadata_is_st4200_every_platform_and_two_libraries(self):
        metadata = self.load("docs/package-control-entry.json")
        self.assertEqual(metadata["name"], "MarkdownGlance")
        release = metadata["releases"][0]
        self.assertEqual(release["sublime_text"], ">=4200")
        self.assertEqual(release["platforms"], ["*"])
        self.assertIs(release["tags"], True)
        self.assertEqual(metadata["labels"], ["markdown", "preview"])
        # The parser and its fence extension come from Package Control, on
        # every platform and host (ADR 0012). Nothing else is installed.
        self.assertEqual(
            self.load("dependencies.json"),
            {"*": {"*": ["Markdown", "pymdown-extensions"]}},
        )
        self.assertFalse(os.path.exists(os.path.join(ROOT, "lib")))

    def test_messages_are_the_install_note_and_nothing_routine(self):
        # Package Control shows a message once and then it is gone, and users
        # do not read a note for every release. Only a change that needs an
        # action from the user earns one, and it stays short and links the
        # changelog. The install note is the exception: it is the one message
        # a first-time user does read, so it has room for the quick start and
        # the key bindings, bounded so it stays one screen.
        messages = self.load("messages.json")
        self.assertEqual(messages["install"], "messages/install.txt")
        with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as source:
            released = set(re.findall(r"^## \[(\d+\.\d+\.\d+)\]", source.read(), re.M))
        for key, path in messages.items():
            self.assertTrue(key == "install" or key in released, key)
            with open(os.path.join(ROOT, path), encoding="utf-8") as source:
                lines = source.read().rstrip("\n").split("\n")
            self.assertLessEqual(len(lines), 50 if key == "install" else 8, path)
            if key != "install":
                self.assertIn("CHANGELOG", "\n".join(lines), path)

    def test_public_command_and_key_context_namespaces_are_unique(self):
        commands = self.load("Default.sublime-commands")
        for item in commands:
            if item["command"] == "edit_settings":
                # The only built-in the palette may reach, and only at this
                # package's own keymap.
                self.assertIn(
                    "${packages}/MarkdownGlance/", item["args"]["base_file"]
                )
                continue
            self.assertTrue(item["command"].startswith("mdglance_"), item["caption"])
        # Developer-only commands stay out of every user's command palette.
        palette = {item["command"] for item in commands}
        self.assertNotIn("mdglance_run_contract_tests", palette)
        self.assertNotIn("mdglance_run_benchmark", palette)
        for platform in PLATFORMS:
            for suffix in BINDINGS:
                name = "Default ({}).{}".format(platform, suffix)
                for item in self.load(name):
                    self.assertTrue(item["command"].startswith("mdglance_"), name)
                    for context in item.get("context", ()):
                        self.assertTrue(context["key"].startswith("mdglance."), name)
                        self.assertIs(context["operand"], True)

    def test_the_zoom_keys_never_fire_without_a_preview_to_zoom(self):
        """`ctrl+=` in a Markdown file with no preview open is Sublime's.

        The binding costs the user their font-size key only for as long as
        there is a preview in the window for it to act on.
        """
        for platform in PLATFORMS:
            name = "Default ({}).sublime-keymap".format(platform)
            for item in self.load(name):
                contexts = {entry["key"] for entry in item.get("context", ())}
                if item["command"] != "mdglance_zoom":
                    continue
                if contexts <= OWN_SURFACE_CONTEXTS:
                    continue
                self.assertIn("mdglance.preview_open", contexts, (name, item["keys"]))
                self.assertIn("mdglance.markdown_source", contexts, name)

    def test_the_reset_zoom_key_stays_out_of_the_source(self):
        # `ctrl+0` falls through to `focus_side_bar`, which has no other key.
        for platform in PLATFORMS:
            name = "Default ({}).sublime-keymap".format(platform)
            for item in self.load(name):
                contexts = {entry["key"] for entry in item.get("context", ())}
                if contexts <= OWN_SURFACE_CONTEXTS:
                    continue
                self.assertNotIn(item["keys"], (["ctrl+0"], ["super+0"]), name)

    def test_single_stroke_bindings_outside_the_preview_are_declared(self):
        # ADR 0009: a single-stroke default outside the preview shadows a key
        # Sublime Text already uses in the buffer being edited, so every one is
        # named here and nowhere else. Bindings that fire only inside a view
        # this package created are unconstrained.
        for platform in PLATFORMS:
            name = "Default ({}).sublime-keymap".format(platform)
            for item in self.load(name):
                contexts = {entry["key"] for entry in item.get("context", ())}
                keys = item["keys"]
                if (contexts and contexts <= OWN_SURFACE_CONTEXTS) or len(keys) > 1:
                    continue
                self.assertIn(keys[0], SINGLE_STROKE_OUTSIDE_PREVIEW, (name, keys))

    def test_platform_bindings_differ_only_by_macos_key_spelling(self):
        for suffix in BINDINGS:
            linux = self.load("Default (Linux).{}".format(suffix))
            self.assertNotEqual(as_macos(linux), linux, suffix)
            self.assertEqual(
                self.load("Default (Windows).{}".format(suffix)), linux, suffix
            )
            self.assertEqual(
                self.load("Default (OSX).{}".format(suffix)), as_macos(linux), suffix
            )

    def test_shipped_settings_keep_mermaid_opt_in(self):
        # The default settings file is what users actually get; a "true" here
        # sends diagram source to mermaid_server without anyone opting in.
        path = os.path.join(ROOT, "MarkdownGlance.sublime-settings")
        with open(path, encoding="utf-8") as source:
            shipped = source.read()
        self.assertIn('"enable_mermaid": false', shipped)
        self.assertNotIn('"enable_mermaid": true', shipped)
        self.assertFalse(RenderSettings().enable_mermaid)

    def test_shipped_settings_keep_math_opt_in(self):
        # Same reason: a "true" here sends formula source to math_server.
        path = os.path.join(ROOT, "MarkdownGlance.sublime-settings")
        with open(path, encoding="utf-8") as source:
            shipped = source.read()
        self.assertIn('"enable_math": false', shipped)
        self.assertNotIn('"enable_math": true', shipped)
        self.assertFalse(RenderSettings().enable_math)

    def test_diagnostics_report_the_released_version(self):
        # A diagnostics paste is worthless if its version is a stale literal,
        # so it is pinned to the newest entry in the changelog.
        path = os.path.join(ROOT, "preview", "adapter", "commands.py")
        with open(path, encoding="utf-8") as source:
            reported = re.search(r'"version": "([^"]+)"', source.read()).group(1)
        with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as source:
            released = re.search(r"^## \[(\d+\.\d+\.\d+)\]", source.read(), re.M)
        self.assertEqual(reported, released.group(1))

    def test_runtime_selector_is_python_38_compatible(self):
        with open(os.path.join(ROOT, ".python-version"), encoding="ascii") as source:
            self.assertEqual(source.read().strip(), "3.8")

    def test_plugin_link_commands_accept_sublime_event_argument(self):
        path = os.path.join(ROOT, "preview", "adapter", "commands.py")
        with open(path, encoding="utf-8") as source:
            module = ast.parse(source.read(), path)
        classes = {
            node.name: node for node in module.body if isinstance(node, ast.ClassDef)
        }
        for name in (
            "MdglanceNavigateCommand",
            "MdglanceOpenRelativeCommand",
            "MdglanceOutlineNavigateCommand",
        ):
            run = next(
                node
                for node in classes[name].body
                if isinstance(node, ast.FunctionDef) and node.name == "run"
            )
            self.assertIn("event", [argument.arg for argument in run.args.args])


if __name__ == "__main__":
    unittest.main()
