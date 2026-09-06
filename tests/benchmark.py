import json
import os
import platform
import statistics
import time

import markdown as markdown_lib
import pymdownx

from MarkdownGlance.preview.application.render_pipeline import render
from MarkdownGlance.preview.domain.contracts import (
    AssetStatus,
    Failed,
    RenderRequest,
    RenderSettings,
    ThemeSnapshot,
)


class OfflineResolver:
    def resolve(self, keys, session_id):
        return {key: Failed(AssetStatus.UNAVAILABLE) for key in keys}


def run(package_root, warmups=3, samples=100):
    fixture = os.path.join(package_root, "tests", "fixtures", "benchmark-100k.md")
    with open(fixture, encoding="utf-8") as source:
        markdown = source.read()
    resolver = OfflineResolver()

    def once(generation):
        request = RenderRequest(
            "benchmark",
            generation,
            markdown,
            os.path.dirname(fixture),
            1.0,
            RenderSettings(),
            ThemeSnapshot(),
            "benchmark-token",
        )
        started = time.perf_counter()
        render(request, resolver)
        return (time.perf_counter() - started) * 1000

    for index in range(warmups):
        once(index)
    timings = [once(warmups + index) for index in range(samples)]
    ordered = sorted(timings)
    p95_index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return {
        "fixture_bytes": len(markdown.encode("utf-8")),
        "warmups": warmups,
        "samples": samples,
        "p50_ms": round(statistics.median(timings), 3),
        "p95_ms": round(ordered[p95_index], 3),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "parser": "Markdown {} + pymdown-extensions {}".format(
            markdown_lib.__version__, pymdownx.__version__
        ),
        "backend": "phantom_view",
        "cpu": platform.processor() or "unknown",
    }


if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(__file__))
    print(json.dumps(run(root), indent=2, sort_keys=True))
