import base64
import io
import json
import os
import shutil
import subprocess
import tempfile
from typing import Callable, Optional

from ..domain.contracts import (
    AssetKey,
    AssetStatus,
    Failed,
    FetchedAsset,
    Ready,
    RenderSettings,
)
from ..domain.paths import HOST
from .images import InvalidImage, detect
from .mermaid import parse_local_mermaid_locator
from .policy import NetworkPolicy
from .svg import SUPERSAMPLE, _hidden_window, zoom_for

# A Mermaid diagram drawn here, as a PNG, by a command line tool the reader
# names (ADR 0022): merman-cli, or mermaid-cli's `mmdc`. The arguments below
# are mmdc's, which merman-cli accepts as well, so either can be named without
# the package having to tell them apart.


class MermaidRenderer:
    """Draws a diagram by running the configured renderer as a child process.

    Out of process for the reasons ADR 0019 gives for the SVG renderer: a run
    that will not finish is killed by its timeout, and a crash takes a child
    down rather than Sublime Text.
    """

    def __init__(
        self,
        run: Optional[Callable[..., subprocess.CompletedProcess]] = None,
        which: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        self._run = run or subprocess.run
        self._which = which or shutil.which

    def backend(self, settings: RenderSettings) -> Optional[str]:
        """The renderer to run, or `None` when the setting names nothing runnable.

        A bare name is looked up on the PATH; anything else is a path. Either
        way it is an executable, never a command line, and the arguments are
        this module's own.
        """
        configured = settings.mermaid_renderer_path.strip()
        if not configured:
            return None
        if os.sep not in configured and "/" not in configured:
            return self._which(configured)
        path = HOST.expand(configured)
        return path if os.access(path, os.X_OK) and os.path.isfile(path) else None

    def _draw(
        self,
        backend: str,
        diagram: str,
        theme: str,
        background: str,
        config_path: str,
        scale: float,
        settings: RenderSettings,
    ) -> Optional[bytes]:
        command = [
            backend,
            "-i",
            "-",
            "-o",
            "-",
            "-e",
            "png",
            "-t",
            theme,
            "-b",
            "#" + background,
            "-c",
            config_path,
            "-s",
            "{:g}".format(scale),
            "-q",
        ]
        # mmdc is a Node script that finds `node` through the PATH, and a
        # Sublime Text started from the Dock has a short one. A global npm
        # install puts the two side by side, so the renderer's own directory
        # goes first.
        environment = dict(os.environ)
        environment["PATH"] = os.pathsep.join(
            (os.path.dirname(backend), environment.get("PATH", ""))
        )
        completed = self._run(
            command,
            input=diagram.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=settings.mermaid_timeout_seconds,
            env=environment,
            **_hidden_window()
        )
        if completed.returncode != 0 or not completed.stdout:
            return None
        return completed.stdout

    def render(self, key: AssetKey, policy: NetworkPolicy):
        """The PNG for a local Mermaid key, as the fetcher answers a URL."""
        settings = policy.settings
        backend = self.backend(settings)
        if backend is None:
            return Failed(AssetStatus.MERMAID_RENDERER_MISSING)
        config_path = None
        try:
            diagram, theme, background, look = parse_local_mermaid_locator(
                key.locator
            )
            # The look reaches the renderer through a configuration file: mmdc
            # has no flag for it, and Mermaid 12 -- which merman follows --
            # draws the gradient-bordered "neo" look unless told otherwise.
            handle, config_path = tempfile.mkstemp(
                prefix="mdglance-mermaid-", suffix=".json"
            )
            with os.fdopen(handle, "w") as config:
                json.dump({"look": look}, config)

            def draw(scale: float) -> Optional[bytes]:
                return self._draw(
                    backend, diagram, theme, background, config_path, scale, settings
                )

            scale = SUPERSAMPLE
            content = draw(scale)
            if content is None:
                return Failed(AssetStatus.DIAGRAM_FAILED)
            info = detect(io.BytesIO(content))
            limit = settings.remote_max_dimension
            if max(info.width, info.height) > limit:
                # Too large at the supersample: draw once more at whatever
                # factor fits, down to one, as the SVG renderer would.
                size = (info.width / scale, info.height / scale)
                scale = zoom_for(size, limit)
                content = draw(scale)
                if content is None:
                    return Failed(AssetStatus.DIAGRAM_FAILED)
                info = detect(io.BytesIO(content))
                if max(info.width, info.height) > limit:
                    return Failed(AssetStatus.TOO_LARGE)
        except subprocess.TimeoutExpired:
            return Failed(AssetStatus.TIMEOUT)
        except InvalidImage:
            return Failed(AssetStatus.DIAGRAM_FAILED)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            return Failed(AssetStatus.UNAVAILABLE)
        finally:
            if config_path is not None:
                _remove(config_path)
        data_uri = "data:{};base64,{}".format(
            info.mime_type, base64.b64encode(content).decode("ascii")
        )
        return Ready(
            FetchedAsset(
                data_uri,
                info.width,
                info.height,
                len(content),
                len(data_uri),
                "file",
                policy.revision,
                scale,
            )
        )


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
