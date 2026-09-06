import base64
import io
import struct
import unittest

from MarkdownGlance.preview.assets.cache import AssetCache
from MarkdownGlance.preview.assets.images import InvalidImage, detect
from MarkdownGlance.preview.assets.policy import NetworkPolicy
from MarkdownGlance.preview.domain.contracts import (
    AssetKey,
    AssetKind,
    AssetStatus,
    Failed,
    FetchedAsset,
    Ready,
    RenderSettings,
)


def png(width=277, height=70):
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00" * 8
        + struct.pack(">II", width, height)
        + b"\x00" * 8
    )


class AssetTest(unittest.TestCase):
    def test_detects_extensionless_png_by_signature(self):
        info = detect(io.BytesIO(png()))
        self.assertEqual(
            (info.mime_type, info.width, info.height), ("image/png", 277, 70)
        )

    def test_detects_gif_and_jpeg_dimensions(self):
        gif = io.BytesIO(b"GIF89a\x03\x00\x04\x00" + b"\x00" * 22)
        jpeg = io.BytesIO(
            b"\xff\xd8\xff\xc0\x00\x11\x08\x00\x05\x00\x06" + b"\x00" * 10
        )
        gif_info = detect(gif)
        jpeg_info = detect(jpeg)
        self.assertEqual((gif_info.width, gif_info.height), (3, 4))
        self.assertEqual((jpeg_info.width, jpeg_info.height), (6, 5))

    def test_rejects_non_image(self):
        with self.assertRaises(InvalidImage):
            detect(io.BytesIO(b"not an image"))

    def test_lru_evicts_by_data_uri_cost(self):
        cache = AssetCache(max_bytes=8)
        one = AssetKey(AssetKind.REMOTE_IMAGE, "https://one.test/a")
        two = AssetKey(AssetKind.REMOTE_IMAGE, "https://two.test/b")
        asset = lambda data: Ready(FetchedAsset(data, 1, 1, 1, len(data), "https", 0))
        cache.put(one, asset("12345"), 0)
        cache.put(two, asset("67890"), 0)
        self.assertIsNone(cache.get(one))
        self.assertIsNotNone(cache.get(two))

    def test_negative_cache_expires(self):
        now = [0.0]
        cache = AssetCache(negative_ttl_s=30, clock=lambda: now[0])
        key = AssetKey(AssetKind.REMOTE_IMAGE, "https://example.test/a")
        cache.put(key, Failed(AssetStatus.UNAVAILABLE), 0)
        now[0] = 31
        self.assertIsNone(cache.get(key))

    def test_policy_blocks_baked_assets_until_they_are_enabled(self):
        diagram = AssetKey(AssetKind.MERMAID, "https://mermaid.test/img/abc")
        formula = AssetKey(AssetKind.MATH, "https://math.test/png.image?x")
        strict = NetworkPolicy(RenderSettings(), 1)
        self.assertEqual(strict.evaluate_key(diagram), AssetStatus.BLOCKED)
        self.assertEqual(strict.evaluate_key(formula), AssetStatus.BLOCKED)
        math_only = NetworkPolicy(RenderSettings(enable_math=True), 2)
        self.assertEqual(math_only.evaluate_key(diagram), AssetStatus.BLOCKED)
        self.assertIsNone(math_only.evaluate_key(formula))

    def test_policy_rechecks_cached_redirect_scheme_and_limits(self):
        key = AssetKey(AssetKind.REMOTE_IMAGE, "https://example.test/a")
        asset = FetchedAsset("data:x", 5000, 10, 50, 6, "http", 0)
        strict = NetworkPolicy(RenderSettings(), 1)
        self.assertEqual(strict.evaluate(key, asset), AssetStatus.BLOCKED)
        insecure = NetworkPolicy(
            RenderSettings(
                allow_insecure_remote_images=True,
                remote_max_dimension=4096,
            ),
            2,
        )
        self.assertEqual(insecure.evaluate(key, asset), AssetStatus.TOO_LARGE)
