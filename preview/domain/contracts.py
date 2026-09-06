from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from os.path import basename
from typing import Optional, Tuple, Union
from urllib.parse import urlsplit


class PreviewMode(Enum):
    SIDE_BY_SIDE = "side_by_side"
    FULL_SCREEN = "full_screen"


class AssetKind(Enum):
    LOCAL_IMAGE = "local_image"
    REMOTE_IMAGE = "remote_image"
    MERMAID = "mermaid"
    MATH = "math"


@dataclass(frozen=True)
class AssetKey:
    kind: AssetKind
    locator: str

    @property
    def safe_label(self) -> str:
        digest = sha256(self.locator.encode("utf-8", "surrogatepass")).hexdigest()[:8]
        if self.kind == AssetKind.LOCAL_IMAGE:
            identity = basename(self.locator) or "local"
        else:
            identity = urlsplit(self.locator).hostname or "remote"
        return "{}:{}:{}".format(self.kind.value, identity, digest)


@dataclass(frozen=True)
class ThemeSnapshot:
    """The source view's palette, and the colour scheme it came from.

    `scheme` is the `(key, value)` pairs a surface has to mirror to resolve the
    same palette itself: minihtml reads `var(--background)` and the rest from
    the colour scheme of the view a phantom sits in, not from the source. A
    Markdown file often carries its own scheme -- MarkdownEditing writes one
    into `Markdown.sublime-settings`, and it wins over the global one -- so a
    surface left on the defaults would follow a different scheme entirely.
    """

    background: str = "#ffffff"
    foreground: str = "#222222"
    is_dark: bool = False
    accent: str = "#4f8cc9"
    scheme: Tuple[Tuple[str, str], ...] = ()


@dataclass(frozen=True)
class RenderSettings:
    update_delay_ms: int = 100
    enable_mermaid: bool = False
    mermaid_server: str = "https://mermaid.ink"
    enable_math: bool = False
    math_server: str = "https://latex.codecogs.com"
    allow_insecure_remote_images: bool = False
    remote_timeout_seconds: float = 15.0
    remote_max_bytes: int = 10 * 1024 * 1024
    remote_max_dimension: int = 4096
    table_max_columns: int = 200
    enable_toc: bool = False
    toc_minimum_length: int = 1200
    toc_minimum_headings: int = 3
    auto_width: bool = True
    debug_logging: bool = False


@dataclass(frozen=True)
class RenderRequest:
    session_id: str
    generation: int
    markdown: str
    base_path: Optional[str]
    zoom: float
    settings: RenderSettings
    theme: ThemeSnapshot
    action_token: str = ""
    # Preview width in px, 0.0 when it cannot be measured yet.
    viewport_width: float = 0.0


@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    slug: str
    ordinal: int
    position_ratio: float


@dataclass(frozen=True)
class SourceHeading:
    """A heading located in the Markdown source, before any rendering."""

    level: int
    text: str
    ordinal: int
    line: int


class DiagnosticStage(Enum):
    PARSE = "parse"
    STRUCTURE = "structure"
    ASSET = "asset"
    SERIALISE = "serialise"


@dataclass(frozen=True)
class RenderDiagnostic:
    stage: DiagnosticStage
    message: str


@dataclass(frozen=True)
class FetchedAsset:
    data_uri: str
    width: int
    height: int
    response_bytes: int
    cache_cost_bytes: int
    effective_scheme: str
    fetched_revision: int


class AssetStatus(Enum):
    LOADING = "loading"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"
    TOO_LARGE = "too_large"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class Ready:
    asset: FetchedAsset


@dataclass(frozen=True)
class Pending:
    pass


@dataclass(frozen=True)
class Failed:
    status: AssetStatus


AssetResult = Union[Ready, Pending, Failed]


@dataclass(frozen=True)
class PreviewDocument:
    generation: int
    body_html: str
    headings: Tuple[Heading, ...]
    asset_dependencies: Tuple[AssetKey, ...]
    pending_assets: Tuple[AssetKey, ...]
    links: Tuple[str, ...]
    diagnostics: Tuple[RenderDiagnostic, ...] = ()
