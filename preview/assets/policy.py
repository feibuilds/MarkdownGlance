from dataclasses import dataclass
from urllib.parse import urlsplit

from ..domain.contracts import (
    AssetKey,
    AssetKind,
    AssetStatus,
    FetchedAsset,
    RenderSettings,
)


@dataclass(frozen=True)
class NetworkPolicy:
    settings: RenderSettings
    revision: int = 0

    def evaluate_key(self, key: AssetKey):
        if key.kind == AssetKind.MERMAID and not self.settings.enable_mermaid:
            return AssetStatus.BLOCKED
        if key.kind == AssetKind.MATH and not self.settings.enable_math:
            return AssetStatus.BLOCKED
        if key.kind == AssetKind.LOCAL_IMAGE:
            return None
        scheme = urlsplit(key.locator).scheme.lower()
        if scheme == "https":
            return None
        if scheme == "http" and self.settings.allow_insecure_remote_images:
            return None
        return AssetStatus.BLOCKED

    def evaluate(self, key: AssetKey, asset: FetchedAsset):
        blocked = self.evaluate_key(key)
        if blocked is not None:
            return blocked
        if asset.from_svg and not self.settings.enable_svg:
            return AssetStatus.UNSUPPORTED_FORMAT
        if (
            asset.effective_scheme == "http"
            and not self.settings.allow_insecure_remote_images
        ):
            return AssetStatus.BLOCKED
        if asset.response_bytes > self.settings.remote_max_bytes:
            return AssetStatus.TOO_LARGE
        if (
            asset.width > self.settings.remote_max_dimension
            or asset.height > self.settings.remote_max_dimension
        ):
            return AssetStatus.TOO_LARGE
        return None
