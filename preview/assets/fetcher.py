import base64
import io
import socket
import ssl
import urllib.error
import urllib.request
from typing import Optional
from urllib.parse import urlsplit

from ..domain.contracts import (
    AssetKey,
    AssetStatus,
    Failed,
    FetchedAsset,
    Ready,
)
from .images import InvalidImage, SvgImage, UnsupportedImage, detect
from .policy import NetworkPolicy
from .svg import SvgRasteriser, SvgRenderFailed


class _RedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allow_insecure: bool) -> None:
        super().__init__()
        self.allow_insecure = allow_insecure
        self.hops = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.hops += 1
        if self.hops > 5:
            raise urllib.error.HTTPError(
                newurl, code, "too many redirects", headers, fp
            )
        old_scheme = urlsplit(req.full_url).scheme.lower()
        new_scheme = urlsplit(newurl).scheme.lower()
        if old_scheme == "https" and new_scheme == "http" and not self.allow_insecure:
            raise PermissionError("HTTPS to HTTP redirect blocked")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ImageFetcher:
    def __init__(self, rasteriser: Optional[SvgRasteriser] = None) -> None:
        self._svg = rasteriser or SvgRasteriser()

    def fetch(self, key: AssetKey, policy: NetworkPolicy):
        settings = policy.settings
        blocked = policy.evaluate_key(key)
        if blocked is not None:
            return Failed(blocked)
        try:
            redirect = _RedirectHandler(settings.allow_insecure_remote_images)
            opener = urllib.request.build_opener(
                redirect,
                urllib.request.HTTPSHandler(context=ssl.create_default_context()),
            )
            request = urllib.request.Request(
                key.locator, headers={"User-Agent": "MarkdownGlance/0.1"}
            )
            with opener.open(
                request, timeout=settings.remote_timeout_seconds
            ) as response:
                declared = response.headers.get("Content-Length")
                if declared is not None and int(declared) > settings.remote_max_bytes:
                    return Failed(AssetStatus.TOO_LARGE)
                chunks = []
                received = 0
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > settings.remote_max_bytes:
                        return Failed(AssetStatus.TOO_LARGE)
                    chunks.append(chunk)
                content = b"".join(chunks)
                scale, drawn = 1.0, False
                try:
                    info = detect(io.BytesIO(content))
                except SvgImage:
                    # Already off the UI thread, so the renderer runs here
                    # rather than being handed on. A badge or a diagram from
                    # the network is drawn with no directory of ours behind
                    # it: nothing local can be pulled into the image.
                    status = self._svg.unavailable(settings)
                    if status is not None:
                        return Failed(status)
                    content, scale = self._svg.rasterise(content, settings)
                    drawn = True
                    info = detect(io.BytesIO(content))
                if (
                    info.width > settings.remote_max_dimension
                    or info.height > settings.remote_max_dimension
                ):
                    return Failed(AssetStatus.TOO_LARGE)
                data_uri = "data:{};base64,{}".format(
                    info.mime_type, base64.b64encode(content).decode("ascii")
                )
                asset = FetchedAsset(
                    data_uri,
                    info.width,
                    info.height,
                    received,
                    len(data_uri),
                    urlsplit(response.geturl()).scheme.lower(),
                    policy.revision,
                    scale,
                    drawn,
                )
                status = policy.evaluate(key, asset)
                return Failed(status) if status is not None else Ready(asset)
        except (TimeoutError, socket.timeout):
            return Failed(AssetStatus.TIMEOUT)
        except PermissionError:
            return Failed(AssetStatus.BLOCKED)
        except SvgRenderFailed:
            return Failed(AssetStatus.RENDER_FAILED)
        except UnsupportedImage:
            return Failed(AssetStatus.UNSUPPORTED_FORMAT)
        except (InvalidImage, OSError, ValueError, urllib.error.URLError):
            return Failed(AssetStatus.UNAVAILABLE)
