import base64
import json
import os
import shutil
import struct
import subprocess
import tempfile
import unittest

from MarkdownGlance.preview.assets.cache import AssetCache
from MarkdownGlance.preview.assets.mermaid import (
    local_mermaid_locator,
    mermaid_locator,
    parse_local_mermaid_locator,
)
from MarkdownGlance.preview.assets.mermaid_local import MermaidRenderer
from MarkdownGlance.preview.assets.policy import NetworkPolicy
from MarkdownGlance.preview.assets.resolver import AssetResolver
from MarkdownGlance.preview.domain.contracts import (
    AssetKey,
    AssetKind,
    AssetStatus,
    Failed,
    Pending,
    Ready,
    RenderRequest,
    RenderSettings,
    ThemeSnapshot,
    is_local_mermaid,
)
from MarkdownGlance.preview.domain.settings import parse_settings
from MarkdownGlance.preview.renderer import parse, serialise

DIAGRAM = "flowchart LR\nA --> B"
DARK = ThemeSnapshot("#1e1e2e", "#cdd6f4", True)
LOCAL = RenderSettings(enable_mermaid=True, mermaid_renderer_path="merman-cli")


def png(width, height):
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", width, height)


class Completed:
    def __init__(self, returncode=0, stdout=None):
        self.returncode = returncode
        self.stdout = png(80, 40) if stdout is None else stdout
        self.stderr = b""


class Runner:
    """A stand-in for `subprocess.run` that records each command line."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes) or [Completed()]
        self.commands = []
        self.inputs = []
        self.kwargs = []
        self.configs = []

    def __call__(self, command, input=None, **kwargs):
        self.commands.append(command)
        if "-c" in command:
            with open(command[command.index("-c") + 1]) as handle:
                self.configs.append(json.load(handle))
        self.inputs.append(input)
        self.kwargs.append(kwargs)
        outcome = self.outcomes[min(len(self.commands), len(self.outcomes)) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def renderer(*outcomes, backend="/opt/bin/merman-cli"):
    runner = Runner(*outcomes)
    return MermaidRenderer(run=runner, which=lambda name: backend), runner


def key(theme=DARK):
    return AssetKey(AssetKind.MERMAID, local_mermaid_locator(DIAGRAM, theme))


def policy(settings=LOCAL):
    return NetworkPolicy(settings, 3)


class LocatorTest(unittest.TestCase):
    def test_round_trip_carries_diagram_and_appearance(self):
        locator = local_mermaid_locator(DIAGRAM, DARK)
        self.assertEqual(
            parse_local_mermaid_locator(locator),
            (DIAGRAM, "dark", "1e1e2e", "classic"),
        )
        neo = local_mermaid_locator(DIAGRAM, DARK, "neo")
        self.assertNotEqual(neo, locator)
        self.assertEqual(parse_local_mermaid_locator(neo)[3], "neo")
        self.assertNotIn(DIAGRAM, AssetKey(AssetKind.MERMAID, locator).safe_label)
        self.assertIn(":local:", AssetKey(AssetKind.MERMAID, locator).safe_label)

    def test_theme_is_part_of_the_locator(self):
        light = local_mermaid_locator(DIAGRAM, ThemeSnapshot())
        self.assertNotEqual(light, local_mermaid_locator(DIAGRAM, DARK))
        self.assertEqual(
            parse_local_mermaid_locator(light)[1:3], ("default", "ffffff")
        )

    def test_the_setting_chooses_between_server_and_local(self):
        server = mermaid_locator(DIAGRAM, RenderSettings(), DARK)
        local = mermaid_locator(DIAGRAM, LOCAL, DARK)
        self.assertTrue(server.startswith("https://mermaid.ink/img/"))
        self.assertFalse(is_local_mermaid(AssetKey(AssetKind.MERMAID, server)))
        self.assertTrue(is_local_mermaid(AssetKey(AssetKind.MERMAID, local)))

    def test_a_server_url_is_not_a_local_locator(self):
        with self.assertRaises(ValueError):
            parse_local_mermaid_locator("https://mermaid.ink/img/abc")


class BackendTest(unittest.TestCase):
    def test_blank_setting_names_no_renderer(self):
        subject, _ = renderer()
        self.assertIsNone(subject.backend(RenderSettings()))

    def test_bare_name_is_looked_up_on_the_path(self):
        looked_up = []
        subject = MermaidRenderer(
            run=Runner(), which=lambda name: looked_up.append(name) or "/x/" + name
        )
        self.assertEqual(subject.backend(LOCAL), "/x/merman-cli")
        self.assertEqual(looked_up, ["merman-cli"])

    def test_a_path_must_be_an_executable_file(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        path = os.path.join(directory, "mmdc")
        with open(path, "w") as handle:
            handle.write("#!/bin/sh\n")
        subject, _ = renderer()
        settings = RenderSettings(mermaid_renderer_path=path)
        if os.name != "nt":
            # Windows has no execute bit: any file that exists passes.
            self.assertIsNone(subject.backend(settings))
        os.chmod(path, 0o755)
        self.assertEqual(subject.backend(settings), path)
        for elsewhere in (directory, os.path.join(directory, "absent")):
            self.assertIsNone(
                subject.backend(RenderSettings(mermaid_renderer_path=elsewhere))
            )


class RenderTest(unittest.TestCase):
    def test_command_line_is_mmdc_compatible_and_reads_stdin(self):
        subject, runner = renderer()
        subject.render(key(), policy())
        command = list(runner.commands[0])
        config_path = command[command.index("-c") + 1]
        command[command.index("-c") + 1] = "<config>"
        self.assertEqual(
            command,
            [
                "/opt/bin/merman-cli",
                "-i",
                "-",
                "-o",
                "-",
                "-e",
                "png",
                "-t",
                "dark",
                "-b",
                "#1e1e2e",
                "-c",
                "<config>",
                "-s",
                "2",
                "-q",
            ],
        )
        # The look goes in a configuration file, removed once drawn.
        self.assertEqual(runner.configs[0], {"look": "classic"})
        self.assertFalse(os.path.exists(config_path))
        self.assertEqual(runner.inputs[0], DIAGRAM.encode("utf-8"))
        kwargs = runner.kwargs[0]
        self.assertEqual(kwargs["timeout"], LOCAL.mermaid_timeout_seconds)
        self.assertTrue(kwargs["env"]["PATH"].startswith("/opt/bin" + os.pathsep))

    def test_the_look_setting_reaches_the_renderer(self):
        subject, runner = renderer()
        neo = AssetKey(AssetKind.MERMAID, local_mermaid_locator(DIAGRAM, DARK, "neo"))
        subject.render(neo, policy())
        self.assertEqual(runner.configs[0], {"look": "neo"})

    def test_drawn_at_the_supersample_and_shown_at_half(self):
        subject, _ = renderer()
        result = subject.render(key(), policy())
        self.assertIsInstance(result, Ready)
        asset = result.asset
        self.assertEqual((asset.width, asset.height), (80, 40))
        self.assertEqual(asset.pixel_scale, 2.0)
        self.assertEqual(asset.effective_scheme, "file")
        self.assertEqual(asset.fetched_revision, 3)
        self.assertFalse(asset.from_svg)
        self.assertTrue(asset.data_uri.startswith("data:image/png;base64,"))

    def test_missing_renderer_is_reported_without_running_anything(self):
        subject, runner = renderer(backend=None)
        result = subject.render(key(), policy())
        self.assertEqual(result, Failed(AssetStatus.MERMAID_RENDERER_MISSING))
        self.assertEqual(runner.commands, [])

    def test_rejected_diagram_and_empty_output_fail_to_draw(self):
        for outcome in (Completed(returncode=1, stdout=b""), Completed(stdout=b"")):
            subject, _ = renderer(outcome)
            self.assertEqual(
                subject.render(key(), policy()), Failed(AssetStatus.DIAGRAM_FAILED)
            )
        subject, _ = renderer(Completed(stdout=b"<svg/>"))
        self.assertEqual(
            subject.render(key(), policy()), Failed(AssetStatus.DIAGRAM_FAILED)
        )

    def test_timeout_and_launch_failure(self):
        subject, _ = renderer(subprocess.TimeoutExpired("merman-cli", 10))
        self.assertEqual(subject.render(key(), policy()), Failed(AssetStatus.TIMEOUT))
        subject, _ = renderer(OSError("exec format error"))
        self.assertEqual(
            subject.render(key(), policy()), Failed(AssetStatus.UNAVAILABLE)
        )

    def test_too_large_at_the_supersample_is_drawn_again_smaller(self):
        settings = RenderSettings(
            enable_mermaid=True, mermaid_renderer_path="merman-cli",
            remote_max_dimension=1000,
        )
        subject, runner = renderer(
            Completed(stdout=png(1600, 400)), Completed(stdout=png(1000, 250))
        )
        result = subject.render(key(), policy(settings))
        self.assertIsInstance(result, Ready)
        self.assertEqual(runner.commands[1][-2], "1.25")
        self.assertEqual(result.asset.pixel_scale, 1.25)

    def test_too_large_even_at_one_is_too_large(self):
        settings = RenderSettings(
            enable_mermaid=True, mermaid_renderer_path="merman-cli",
            remote_max_dimension=1000,
        )
        subject, runner = renderer(
            Completed(stdout=png(4000, 400)), Completed(stdout=png(2000, 200))
        )
        result = subject.render(key(), policy(settings))
        self.assertEqual(result, Failed(AssetStatus.TOO_LARGE))
        self.assertEqual(runner.commands[1][-2], "1")


class PolicyTest(unittest.TestCase):
    def test_local_diagram_needs_mermaid_enabled_and_nothing_else(self):
        self.assertIsNone(policy().evaluate_key(key()))
        self.assertEqual(
            policy(RenderSettings(mermaid_renderer_path="merman-cli")).evaluate_key(
                key()
            ),
            AssetStatus.BLOCKED,
        )


class ManualExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, fn, key, policy):
        from concurrent.futures import Future

        future = Future()
        self.calls.append((fn, key, policy, future))
        return future


class ResolverTest(unittest.TestCase):
    def test_local_diagram_goes_to_the_renderer_off_the_calling_thread(self):
        subject, _ = renderer()
        executor = ManualExecutor()
        resolver = AssetResolver(
            AssetCache(),
            object(),
            lambda: policy(),
            executor,
            lambda callback: callback(),
            lambda key, waiters: None,
            mermaid=subject,
        )
        result = resolver.resolve([key()], "one")[key()]
        self.assertIsInstance(result, Pending)
        self.assertEqual(executor.calls[0][0], subject.render)


class ParseAndSerialiseTest(unittest.TestCase):
    def request(self, settings):
        return RenderRequest(
            "session", 1, "```mermaid\n" + DIAGRAM + "\n```\n", None, 1.0,
            settings, DARK,
        )

    def test_local_diagram_has_no_privacy_caption(self):
        parsed = parse(self.request(LOCAL), mermaid_url_builder=mermaid_locator)
        [asset_key] = parsed.asset_keys
        self.assertTrue(is_local_mermaid(asset_key))
        html = serialise(
            parsed, {asset_key: Pending()}, self.request(LOCAL)
        ).body_html
        self.assertNotIn("is sent to", html)
        self.assertIn("Loading", html)

    def test_missing_renderer_says_what_to_set(self):
        parsed = parse(self.request(LOCAL), mermaid_url_builder=mermaid_locator)
        failed = {k: Failed(AssetStatus.MERMAID_RENDERER_MISSING) for k in parsed.asset_keys}
        html = serialise(parsed, failed, self.request(LOCAL)).body_html
        self.assertIn("No Mermaid renderer", html)
        self.assertIn("mermaid_renderer_path", html)


class SettingsTest(unittest.TestCase):
    def test_look_is_classic_unless_neo_is_chosen(self):
        warnings = []
        self.assertEqual(parse_settings({}).mermaid_look, "classic")
        self.assertEqual(parse_settings({"mermaid_look": "neo"}).mermaid_look, "neo")
        self.assertEqual(
            parse_settings({"mermaid_look": "fancy"}, warnings.append).mermaid_look,
            "classic",
        )
        self.assertEqual(len(warnings), 1)

    def test_server_payload_carries_the_look(self):
        url = mermaid_locator(DIAGRAM, RenderSettings(mermaid_look="neo"), DARK)
        encoded = url.split("/img/", 1)[1].split("?", 1)[0]
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        self.assertEqual(payload["mermaid"], {"theme": "dark", "look": "neo"})

    def test_renderer_path_and_timeout_are_parsed(self):
        warnings = []
        settings = parse_settings(
            {"mermaid_renderer_path": "~/bin/mmdc", "mermaid_timeout_seconds": 30},
            warnings.append,
        )
        self.assertEqual(settings.mermaid_renderer_path, "~/bin/mmdc")
        self.assertEqual(settings.mermaid_timeout_seconds, 30)
        self.assertEqual(warnings, [])
        settings = parse_settings(
            {"mermaid_renderer_path": ["mmdc"], "mermaid_timeout_seconds": "slow"},
            warnings.append,
        )
        self.assertEqual(settings.mermaid_renderer_path, "")
        self.assertEqual(settings.mermaid_timeout_seconds, 10.0)
        self.assertEqual(len(warnings), 2)


@unittest.skipUnless(shutil.which("merman-cli"), "merman-cli is not installed")
class MermanIntegrationTest(unittest.TestCase):
    def test_merman_draws_a_png(self):
        result = MermaidRenderer().render(key(), policy())
        self.assertIsInstance(result, Ready)
        self.assertGreater(result.asset.width, 0)

    def test_merman_rejects_a_broken_diagram(self):
        broken = AssetKey(
            AssetKind.MERMAID, local_mermaid_locator("flowchart LR\nA -->", DARK)
        )
        result = MermaidRenderer().render(broken, policy())
        self.assertEqual(result, Failed(AssetStatus.DIAGRAM_FAILED))
