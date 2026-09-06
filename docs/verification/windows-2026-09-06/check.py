#!/usr/bin/env python3
"""Assert what the Windows run's exported pages must contain.

The probe posted the pages the real `MarkdownGlance: Open in Browser` command
wrote inside the guest; this reads them back on the host and states pass or
fail per claim, so the verification note quotes checks rather than adjectives.

    python3 check.py [evidence-dir]
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# The fixture lives in a directory whose name has a space and a hash; both
# have to survive into the URL the page gives the image.
ENCODED_DIR = "fixture%20space%20%23hash"
KATEX = "cdn.jsdelivr.net/npm/katex@0.16.22"
MERMAID = "cdn.jsdelivr.net/npm/mermaid@11.12.0"


def load(directory, name):
    path = os.path.join(directory, name)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def checks_for_export(page, saved):
    """Claims that hold for the export-check fixture, saved or unsaved."""
    image = re.search(r'<img alt="Relative image" src="([^"]+)"', page)
    src = image.group(1) if image else ""
    yield "image src found", bool(src), src
    if saved:
        yield "image resolved beside the source", src.startswith("file:///C:/"), src
        yield "space and hash encoded in the URL", ENCODED_DIR in src, src
        yield "no drive letter left bare", "C:\\" not in src, src
    else:
        # An unsaved buffer has no directory, so the relative URL stays as it
        # was written; image resolution is not claimed for that case.
        yield "unsaved keeps the relative src", src == "pixel.png", src

    yield "no <base> element", "<base" not in page, ""
    yield 'heading id "same"', 'id="same"' in page, ""
    yield 'heading id "same-2"', 'id="same-2"' in page, ""
    yield "link to #same", 'href="#same"' in page, ""
    yield "link to #same-2", 'href="#same-2"' in page, ""
    yield "table rows", page.count("<tr>") == 3, str(page.count("<tr>"))
    yield "right-aligned cell", 'align="right"' in page or "text-align: right" in page, ""
    yield "nested list", re.search(r"<li>Parent one\s*<ul>", page) is not None, ""
    yield (
        "fenced python inside a list item",
        re.search(r'<li>\s*<p>Ordered one</p>.*?<code class="language-python">', page, re.S)
        is not None,
        "",
    )
    yield "mermaid fence became a diagram element", '<pre class="mermaid">' in page, ""
    yield "mermaid arrows survive as entities", "--&gt;" in page, ""
    yield "mermaid script pinned", MERMAID in page, ""
    yield "katex stylesheet pinned", KATEX in page, ""
    yield "integrity on every cdn tag", page.count("integrity=") == 4, str(page.count("integrity="))
    yield "arithmatex inline formula", 'class="arithmatex">\\(' in page, ""
    yield "arithmatex display formula", 'class="arithmatex">\\[' in page, ""
    yield "prose dollars left alone", "It costs $5 and $6" in page, ""


def checks_for_plain(page):
    yield "title is the plain fixture", "<title>plain-export.md</title>" in page, ""
    yield "no katex", KATEX not in page, ""
    yield "no mermaid", MERMAID not in page, ""
    yield "no render script", "renderMathInElement" not in page, ""
    yield "no integrity tags", "integrity=" not in page, ""
    yield "the fence still rendered", 'class="language-python"' in page, ""


def main():
    directory = sys.argv[1] if len(sys.argv) > 1 else HERE
    results = []

    saved = load(directory, "p1-export-saved.html")
    other = load(directory, "p2-export-other-theme.html")
    plain = load(directory, "p3-export-plain.html")
    unsaved = load(directory, "p4-export-unsaved.html")

    groups = [
        ("p1 saved file", saved, lambda page: checks_for_export(page, True)),
        ("p2 other system theme", other, lambda page: checks_for_export(page, True)),
        ("p3 page with neither", plain, checks_for_plain),
        ("p4 unsaved buffer", unsaved, lambda page: checks_for_export(page, False)),
    ]
    for label, page, produce in groups:
        if page is None:
            results.append((label, "page missing", False, ""))
            continue
        for claim, ok, detail in produce(page):
            results.append((label, claim, bool(ok), detail))

    # The page is one file per source path, so both theme runs must be the
    # same document: the theme lives in the browser, not in the export.
    if saved and other:
        results.append(
            ("p1 vs p2", "the same page served both themes", saved == other, "")
        )

    if saved:
        results.append(
            ("p1 saved file", "title is the file name",
             "<title>export-check.md</title>" in saved, "")
        )
    if unsaved:
        results.append(
            ("p4 unsaved buffer", "title is Untitled",
             "<title>Untitled</title>" in unsaved, "")
        )

    failed = [row for row in results if not row[2]]
    for label, claim, ok, detail in results:
        print("{}  {:24} {}{}".format(
            "PASS" if ok else "FAIL", label, claim,
            "  [{}]".format(detail) if detail and not ok else ""))
    print("\n{} checks, {} failed".format(len(results), len(failed)))

    with open(os.path.join(directory, "export-checks.json"), "w", encoding="utf-8") as sink:
        json.dump(
            {
                "total": len(results),
                "failed": len(failed),
                "results": [
                    {"group": label, "claim": claim, "pass": ok, "detail": detail}
                    for label, claim, ok, detail in results
                ],
            },
            sink,
            indent=2,
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
