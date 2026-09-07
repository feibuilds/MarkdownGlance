import io
import socket
import unittest
from unittest.mock import patch

from MarkdownGlance.preview.assets.fetcher import ImageFetcher, _RedirectHandler
from MarkdownGlance.preview.assets.policy import NetworkPolicy
from MarkdownGlance.preview.assets.svg import SvgRenderFailed
from MarkdownGlance.preview.domain.contracts import (
    AssetKey,
    AssetKind,
    AssetStatus,
    Failed,
    Ready,
    RenderSettings,
)

PNG = (
    b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + b"\x00\x00\x00\x01\x00\x00\x00\x02" + b"x" * 8
)

BADGE = b'<svg xmlns="http://www.w3.org/2000/svg" width="88" height="20"/>'


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


class Response(io.BytesIO):
    def __init__(self, content, url="https://example.test/image", length=None):
        super().__init__(content)
        self._url = url
        self.headers = {}
        if length is not None:
            self.headers["Content-Length"] = str(length)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def geturl(self):
        return self._url


class Opener:
    def __init__(self, response):
        self.response = response

    def open(self, request, timeout):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FetcherTest(unittest.TestCase):
    def setUp(self):
        self.key = AssetKey(AssetKind.REMOTE_IMAGE, "https://example.test/image")

    def fetch(self, response, settings=RenderSettings(), rasteriser=None):
        with patch(
            "MarkdownGlance.preview.assets.fetcher.urllib.request.build_opener",
            return_value=Opener(response),
        ):
            return ImageFetcher(rasteriser or FakeRasteriser()).fetch(
                self.key, NetworkPolicy(settings)
            )

    def test_success_uses_signature_and_effective_scheme(self):
        result = self.fetch(Response(PNG))
        self.assertIsInstance(result, Ready)
        self.assertEqual((result.asset.width, result.asset.height), (1, 2))
        self.assertEqual(result.asset.effective_scheme, "https")

    def test_declared_and_streamed_oversize_are_rejected(self):
        settings = RenderSettings(remote_max_bytes=1024)
        declared = self.fetch(Response(PNG, length=2048), settings)
        streamed = self.fetch(Response(PNG * 40), settings)
        self.assertEqual(declared, Failed(AssetStatus.TOO_LARGE))
        self.assertEqual(streamed, Failed(AssetStatus.TOO_LARGE))

    def test_timeout_and_invalid_payload_are_typed_failures(self):
        self.assertEqual(self.fetch(socket.timeout()), Failed(AssetStatus.TIMEOUT))
        self.assertEqual(
            self.fetch(Response(b"not an image")), Failed(AssetStatus.UNAVAILABLE)
        )

    def test_a_remote_svg_is_drawn_here_with_no_directory_behind_it(self):
        # The badges at the top of a README are the common case, and they are
        # SVG. The bytes are fetched under the same limits as any image and
        # then drawn locally; nothing about the image is sent anywhere else,
        # and a relative reference inside it resolves against no directory of
        # this machine.
        rasteriser = FakeRasteriser()
        result = self.fetch(Response(BADGE), rasteriser=rasteriser)
        self.assertIsInstance(result, Ready)
        self.assertEqual(result.asset.pixel_scale, 2.0)
        self.assertEqual(result.asset.response_bytes, len(BADGE))
        self.assertEqual(rasteriser.calls, [(BADGE, None)])

    def test_a_remote_svg_without_a_renderer_says_which_failure_it_was(self):
        missing = FakeRasteriser(status=AssetStatus.SVG_RENDERER_MISSING)
        broken = FakeRasteriser(error=SvgRenderFailed("no"))
        self.assertEqual(
            self.fetch(Response(BADGE), rasteriser=missing),
            Failed(AssetStatus.SVG_RENDERER_MISSING),
        )
        self.assertEqual(
            self.fetch(Response(BADGE), rasteriser=broken),
            Failed(AssetStatus.RENDER_FAILED),
        )

    def test_https_downgrade_redirect_is_blocked(self):
        handler = _RedirectHandler(False)
        request = type("Request", (), {"full_url": "https://example.test/a"})()
        with self.assertRaises(PermissionError):
            handler.redirect_request(
                request, None, 302, "Found", {}, "http://example.test/b"
            )


if __name__ == "__main__":
    unittest.main()
