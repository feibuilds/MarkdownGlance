"""Host path handling behind a swappable flavour."""

import os.path
from typing import Any


class PathFlavour:
    def __init__(self, module: Any = os.path) -> None:
        self.module = module

    def expand(self, source: str) -> str:
        return self.module.expanduser(source)

    def is_absolute(self, path: str) -> bool:
        return self.module.isabs(path)

    def drive(self, path: str) -> str:
        """The `X:` a path starts with, or "" on a flavour without drives.

        A UNC root is deliberately not a drive: `splitdrive` hands back the
        whole `//host/share` for one, and a document that names a share must
        not be read as a local file.
        """
        found = self.module.splitdrive(path)[0]
        return found if len(found) == 2 and found.endswith(":") else ""

    def is_drive_absolute(self, path: str) -> bool:
        """`C:/x` and `C:\\x`, which `urlsplit` reads as the scheme `c`."""
        return bool(self.drive(path)) and self.is_absolute(path)

    def from_url_path(self, path: str) -> str:
        """The path of a `file:` URL as a host path.

        `file:///C:/x` arrives as `/C:/x`. That leading separator belongs to
        the URL grammar rather than to the path, and `realpath` would
        otherwise root it on the current drive as `\\C:\\x`.
        """
        return path[1:] if path[:1] == "/" and self.is_drive_absolute(path[1:]) else path

    def normalise(self, path: str) -> str:
        return self.module.realpath(path)

    # Expansion precedes the join: a tilde only starts a path of its own.
    def resolve(self, base_path: str, source: str) -> str:
        return self.module.realpath(self.module.join(base_path, self.expand(source)))


HOST = PathFlavour()
