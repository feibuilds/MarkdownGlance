import os
import tempfile
import unittest
from concurrent.futures import Future

from MarkdownGlance.preview.assets.cache import AssetCache
from MarkdownGlance.preview.assets.policy import NetworkPolicy
from MarkdownGlance.preview.assets.resolver import AssetResolver
from MarkdownGlance.preview.assets.svg import SvgRenderFailed
from MarkdownGlance.preview.domain.contracts import (
    AssetKey,
    AssetKind,
    AssetStatus,
    Failed,
    FetchedAsset,
    Pending,
    Ready,
    RenderSettings,
)


class ManualExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, fn, key, policy):
        future = Future()
        self.calls.append((fn, key, policy, future))
        return future

    def complete(self, index, result):
        self.calls[index][3].set_result(result)

    def fail(self, index, error):
        self.calls[index][3].set_exception(error)


class FakeFetcher:
    def fetch(self, key, policy):
        raise AssertionError("manual executor does not run fetch")


PNG = (
    b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + b"\x00\x00\x00\x50\x00\x00\x00\x28" + b"x" * 8
)

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"/>'


class FakeRasteriser:
    """A renderer without a process behind it."""

    def __init__(self, status=None, error=None):
        self.status = status
        self.error = error
        self.calls = []

    def unavailable(self, settings):
        return self.status

    def rasterise(self, content, settings, base_dir=None):
        self.calls.append((content, base_dir))
        if self.error is not None:
            raise self.error
        return PNG, 2.0


def asset(revision=0, scheme="https", size=10, width=10):
    return Ready(
        FetchedAsset(
            "data:image/png;base64,AA==", width, 10, size, 30, scheme, revision
        )
    )


class ResolverTest(unittest.TestCase):
    def setUp(self):
        self.revision = 0
        self.settings = RenderSettings()
        self.executor = ManualExecutor()
        self.available = []
        self.cache = AssetCache()
        self.rasteriser = FakeRasteriser()
        self.resolver = AssetResolver(
            self.cache,
            FakeFetcher(),
            lambda: NetworkPolicy(self.settings, self.revision),
            self.executor,
            lambda callback: callback(),
            lambda key, waiters: self.available.append((key, waiters)),
            self.rasteriser,
        )
        self.key = AssetKey(AssetKind.REMOTE_IMAGE, "https://example.test/image")

    def test_concurrent_requests_deduplicate_and_wake_both_waiters(self):
        first = self.resolver.resolve([self.key], "one")
        second = self.resolver.resolve([self.key], "two")
        self.assertIsInstance(first[self.key], Pending)
        self.assertIsInstance(second[self.key], Pending)
        self.assertEqual(len(self.executor.calls), 1)
        self.executor.complete(0, asset())
        self.assertEqual(self.available, [(self.key, {"one", "two"})])
        self.assertIsInstance(
            self.resolver.resolve([self.key], "three")[self.key], Ready
        )

    def test_forgotten_waiter_is_not_woken(self):
        self.resolver.resolve([self.key], "forgotten")
        self.resolver.forget_session("forgotten")
        self.executor.complete(0, asset())
        self.assertEqual(self.available, [])
        self.assertIsNotNone(self.cache.get(self.key))

    def test_permitting_policy_change_during_fetch_resubmits(self):
        self.resolver.resolve([self.key], "one")
        self.revision = 1
        self.executor.complete(0, asset(revision=0))
        self.assertEqual(len(self.executor.calls), 2)
        self.assertEqual(self.available, [])
        self.executor.complete(1, asset(revision=1))
        self.assertEqual(self.available, [(self.key, {"one"})])

    def test_blocking_policy_change_during_fetch_wakes_once(self):
        self.resolver.resolve([self.key], "one")
        self.settings = RenderSettings(allow_insecure_remote_images=False)
        self.revision = 1
        self.executor.complete(0, asset(revision=0, scheme="http"))
        self.assertEqual(self.available, [(self.key, {"one"})])
        entry = self.cache.get(self.key)
        self.assertIsInstance(entry.result, Failed)
        self.assertEqual(entry.result.status, AssetStatus.BLOCKED)

    def test_tightened_limit_reclassifies_cache_without_fetch(self):
        self.cache.put(self.key, asset(size=100), 0)
        self.settings = RenderSettings(remote_max_bytes=50)
        self.revision = 1
        result = self.resolver.resolve([self.key], "one")[self.key]
        self.assertIsInstance(result, Failed)
        self.assertEqual(result.status, AssetStatus.TOO_LARGE)
        self.assertEqual(len(self.executor.calls), 0)

    def _local_svg(self, directory, name="diagram.svg", content=SVG):
        path = os.path.join(directory, name)
        with open(path, "wb") as handle:
            handle.write(content)
        return AssetKey(AssetKind.LOCAL_IMAGE, path)

    def test_a_local_svg_is_drawn_off_the_calling_thread(self):
        # A local PNG is read where it is asked for; an SVG needs a renderer,
        # which is a process, so it goes to the pool like a remote image and
        # the reader sees "Loading" until the drawing comes back.
        with tempfile.TemporaryDirectory() as directory:
            key = self._local_svg(directory)
            first = self.resolver.resolve([key], "one")[key]
            self.assertIsInstance(first, Pending)
            self.assertEqual(len(self.executor.calls), 1)
            job, submitted, policy, _ = self.executor.calls[0]
            self.executor.complete(0, job(submitted, policy))
            self.assertEqual(self.available, [(key, {"one"})])
            result = self.resolver.resolve([key], "one")[key]
            self.assertIsInstance(result, Ready)
            self.assertEqual((result.asset.width, result.asset.height), (80, 40))
            self.assertEqual(result.asset.pixel_scale, 2.0)
            # The directory the file sits in travels with it, so that an
            # `<image>` inside the drawing finds its sibling.
            self.assertEqual(self.rasteriser.calls, [(SVG, directory)])

    def test_a_local_png_is_still_read_without_a_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            key = self._local_svg(directory, "shot.png", PNG)
            result = self.resolver.resolve([key], "one")[key]
        self.assertIsInstance(result, Ready)
        self.assertEqual(result.asset.pixel_scale, 1.0)
        self.assertEqual(len(self.executor.calls), 0)

    def test_no_renderer_and_a_failed_drawing_are_different_answers(self):
        self.rasteriser.status = AssetStatus.SVG_RENDERER_MISSING
        with tempfile.TemporaryDirectory() as directory:
            key = self._local_svg(directory)
            missing = self.resolver.resolve([key], "one")[key]
            self.assertEqual(missing, Failed(AssetStatus.SVG_RENDERER_MISSING))
            self.assertEqual(len(self.executor.calls), 0)

            # Installing one is a settings change, which lifts the answer that
            # depended on it rather than leaving it in the cache.
            self.rasteriser.status = None
            self.rasteriser.error = SvgRenderFailed("bad drawing")
            self.revision = 1
            self.assertIsInstance(self.resolver.resolve([key], "one")[key], Pending)
            job, submitted, policy, _ = self.executor.calls[0]
            self.executor.complete(0, job(submitted, policy))
            self.assertEqual(
                self.resolver.resolve([key], "one")[key],
                Failed(AssetStatus.RENDER_FAILED),
            )

    def test_turning_the_renderer_off_puts_the_placeholder_back(self):
        # A drawing already made is still a PNG, but the setting says the
        # preview does not draw SVGs, and the reader is told so again.
        with tempfile.TemporaryDirectory() as directory:
            key = self._local_svg(directory)
            self.resolver.resolve([key], "one")
            job, submitted, policy, _ = self.executor.calls[0]
            self.executor.complete(0, job(submitted, policy))
            self.assertIsInstance(self.resolver.resolve([key], "one")[key], Ready)
            self.settings = RenderSettings(enable_svg=False)
            self.revision = 1
            self.assertEqual(
                self.resolver.resolve([key], "one")[key],
                Failed(AssetStatus.UNSUPPORTED_FORMAT),
            )

    def test_svg_rendering_turned_off_names_the_format_instead(self):
        self.rasteriser.status = AssetStatus.UNSUPPORTED_FORMAT
        with tempfile.TemporaryDirectory() as directory:
            key = self._local_svg(directory)
            result = self.resolver.resolve([key], "one")[key]
        self.assertEqual(result, Failed(AssetStatus.UNSUPPORTED_FORMAT))
        self.assertEqual(len(self.executor.calls), 0)

    def test_unexpected_fetch_exception_becomes_unavailable(self):
        self.resolver.resolve([self.key], "one")
        self.executor.fail(0, RuntimeError("secret fetch failure"))
        self.assertEqual(self.available, [(self.key, {"one"})])
        entry = self.cache.get(self.key)
        self.assertIsInstance(entry.result, Failed)
        self.assertEqual(entry.result.status, AssetStatus.UNAVAILABLE)
