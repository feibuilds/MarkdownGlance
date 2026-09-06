import base64
import json
import os.path
import unittest

from MarkdownGlance.preview.application.render_pipeline import render
from MarkdownGlance.preview.assets.mermaid import background_hex, mermaid_image_url
from MarkdownGlance.preview.domain.contracts import (
    AssetStatus,
    Failed,
    FetchedAsset,
    Ready,
    RenderRequest,
    RenderSettings,
    ThemeSnapshot,
)
from MarkdownGlance.preview.renderer import parse, serialise
from MarkdownGlance.preview.renderer.stylesheet import represent
from MarkdownGlance.preview.renderer.toc import build_toc

# A base path that is absolute on every host, so the suite runs from any of them.
BASE_PATH = os.path.realpath(os.path.abspath(os.sep + "mdglance"))


class FakeResolver:
    def __init__(self, result=None):
        self.result = result or Failed(AssetStatus.UNAVAILABLE)

    def resolve(self, keys, session_id):
        return {key: self.result for key in keys}


def request(markdown, zoom=1.0, settings=None, token="opaque-token", theme=None):
    return RenderRequest(
        "session",
        7,
        markdown,
        BASE_PATH,
        zoom,
        settings or RenderSettings(),
        theme or ThemeSnapshot(),
        token,
    )


class RendererTest(unittest.TestCase):
    def test_characterized_markdown_dialect(self):
        markdown = """# Title

Paragraph with *emphasis*, **strong**, `code`, and [site](https://example.test).

> Quote

- one
- two

```python
print("hello")
```

Unicode: 中文 café 😀
"""
        document = render(request(markdown), FakeResolver())
        for expected in (
            "<h1",
            "<em>emphasis</em>",
            "<strong>strong</strong>",
            "<blockquote>",
            "<ul>",
            'class="python"',
            "中文 café 😀",
        ):
            self.assertIn(expected, document.body_html)

    def test_duplicate_headings_have_stable_unique_slugs(self):
        document = render(request("# Same\n\n# Same\n\n## Same\n"), FakeResolver())
        self.assertEqual(
            [heading.slug for heading in document.headings],
            ["same", "same-2", "same-3"],
        )
        self.assertIn('id="same-3"', document.body_html)

    def test_raw_html_is_allowlisted_and_source_actions_are_blocked(self):
        markdown = """<script>steal()</script>
<p style="position:fixed" onclick="steal()">safe</p>
[run](subl:evil) [js](javascript:evil) [file](file:///secret)
"""
        body = render(request(markdown), FakeResolver()).body_html
        self.assertNotIn("script", body)
        self.assertNotIn("onclick", body)
        self.assertNotIn("style=", body)
        self.assertNotIn("subl:evil", body)
        self.assertNotIn("javascript:", body)
        self.assertNotIn("file:///secret", body)
        self.assertEqual(body.count('class="blocked-link"'), 3)

    def test_relative_link_uses_opaque_index_and_token(self):
        document = render(request("[next](notes/next.md)"), FakeResolver())
        self.assertEqual(document.links, ("notes/next.md",))
        self.assertIn("mdglance_open_relative", document.body_html)
        self.assertIn("opaque-token", document.body_html)
        self.assertNotIn("notes/next.md", document.body_html)

    def test_body_html_is_zoom_independent(self):
        first = render(request("# Zoom", zoom=1.0), FakeResolver())
        second = render(request("# Zoom", zoom=2.0), FakeResolver())
        self.assertEqual(first.body_html, second.body_html)
        self.assertNotEqual(
            represent(first.body_html, ThemeSnapshot(), 1.0, ""),
            represent(second.body_html, ThemeSnapshot(), 2.0, ""),
        )

    def test_mermaid_is_opt_in_and_encodes_expected_payload(self):
        markdown = "```mermaid\nflowchart LR\nA --> B\n```\n"
        disabled = render(request(markdown), FakeResolver()).body_html
        self.assertIn('class="mermaid"', disabled)
        enabled_settings = RenderSettings(enable_mermaid=True)
        parsed = parse(
            request(markdown, settings=enabled_settings),
            mermaid_url_builder=mermaid_image_url,
        )
        key = parsed.asset_keys[0]
        encoded = key.locator.split("/img/", 1)[1].split("?", 1)[0]
        encoded += "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded))
        self.assertEqual(payload["code"], "flowchart LR\nA --> B")
        self.assertNotIn(payload["code"], key.safe_label)

    def test_mermaid_theme_and_background_follow_the_colour_scheme(self):
        markdown = "```mermaid\nflowchart LR\nA --> B\n```\n"
        settings = RenderSettings(enable_mermaid=True)

        def locator(theme):
            parsed = parse(
                request(markdown, settings=settings, theme=theme),
                mermaid_url_builder=mermaid_image_url,
            )
            return parsed.asset_keys[0].locator

        def diagram_theme(url):
            encoded = url.split("/img/", 1)[1].split("?", 1)[0]
            encoded += "=" * (-len(encoded) % 4)
            return json.loads(base64.urlsafe_b64decode(encoded))["mermaid"]["theme"]

        light = locator(ThemeSnapshot("#ffffff", "#222222", False))
        dark = locator(ThemeSnapshot("#1e1e2eff", "#cdd6f4", True))
        self.assertEqual(diagram_theme(light), "default")
        self.assertEqual(diagram_theme(dark), "dark")
        self.assertIn("bgColor=ffffff", light)
        self.assertIn("bgColor=1e1e2e", dark)
        # The theme is part of the locator, so switching scheme is a new asset.
        self.assertNotEqual(light, dark)

    def test_mermaid_background_falls_back_when_the_colour_is_unusable(self):
        self.assertEqual(background_hex(ThemeSnapshot("#abc", is_dark=False)), "aabbcc")
        self.assertEqual(background_hex(ThemeSnapshot("rgb(1,2,3)")), "ffffff")
        self.assertEqual(
            background_hex(ThemeSnapshot("rgb(1,2,3)", is_dark=True)), "1e1e1e"
        )

    def test_ready_image_uses_intrinsic_rem_size_without_viewport(self):
        parsed = parse(request("![alt](image.png)"))
        asset = FetchedAsset("data:image/png;base64,AA==", 320, 160, 1, 30, "file", 0)
        document = serialise(parsed, {parsed.asset_keys[0]: Ready(asset)}, request("x"))
        self.assertIn("width: 20.0000rem", document.body_html)
        self.assertIn("height: 10.0000rem", document.body_html)

    def test_remote_image_url_is_canonical_and_credentials_are_rejected(self):
        canonical = parse(request("![x](HTTPS://Example.TEST:443/a.png?q=1#frag)"))
        self.assertEqual(
            canonical.asset_keys[0].locator, "https://example.test/a.png?q=1"
        )
        credentialed = parse(request("![x](https://user:secret@example.test/a.png)"))
        self.assertEqual(credentialed.asset_keys, ())

    def test_local_image_url_is_decoded_canonical_and_not_a_network_path(self):
        local = parse(request("![x](images/a%20b.png?ignored=1#fragment)"))
        self.assertEqual(
            local.asset_keys[0].locator,
            os.path.join(BASE_PATH, "images", "a b.png"),
        )
        network_path = parse(request("![x](//server/share/image.png)"))
        self.assertEqual(network_path.asset_keys, ())

    def test_toc_preserves_hierarchy_and_uses_token(self):
        document = render(request("# A\n\n## B\n\n### C\n"), FakeResolver())
        html = build_toc(document.headings, "token", "c")
        self.assertIn("table-of-contents-active", html)
        self.assertIn("table-of-contents-ancestor", html)
        self.assertIn("mdglance_navigate", html)
        self.assertIn("token", html)

    def test_malformed_markdown_does_not_raise(self):
        document = render(request("# [broken\n\n<div><b>still text"), FakeResolver())
        self.assertTrue(document.body_html)


class PreWhitespaceTest(unittest.TestCase):
    """Indentation in a code block survives minihtml's whitespace collapsing.

    It used to be held by one `<i class="space">.</i>` element per space, which
    cost minihtml a layout box each; a run of U+00A0 holds the same width for
    no boxes at all. See `minihtml._pre_text`.
    """

    def body(self, markdown):
        return render(request(markdown), FakeResolver()).body_html

    def test_indentation_is_kept_as_no_break_spaces(self):
        html = self.body("```\ndef f():\n    return 1\n```\n")
        self.assertIn("    return 1", html)

    def test_a_single_space_stays_a_breakable_space(self):
        # minihtml collapses runs, not lone spaces, and a plain space is the
        # only place a long code line may wrap.
        html = self.body("```\nalpha beta gamma\n```\n")
        self.assertIn("alpha beta gamma", html)

    def test_no_element_is_emitted_per_space(self):
        html = self.body("```\n        deep\n```\n")
        self.assertNotIn("<i", html)
        self.assertEqual(html.count(" "), 8)

    def test_newlines_still_become_breaks(self):
        html = self.body("```\none\ntwo\n```\n")
        self.assertIn("one<br />two", html)

    def test_markup_in_a_code_block_is_still_escaped(self):
        html = self.body("```\n  <script>x</script>\n```\n")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


class DialectTest(unittest.TestCase):
    """What markdown2 rendered that Python-Markdown alone would not.

    ADR 0012 moved the parser to the Package Control `Markdown` library; these
    are the GitHub-flavoured shapes that move kept rendering.
    """

    def body(self, markdown):
        return render(request(markdown), FakeResolver()).body_html

    def test_two_column_nested_list_nests(self):
        html = self.body("- a\n  - b\n- c\n")
        self.assertIn("<li>a<ul><li>b</li></ul></li>", html.replace("\n", ""))

    def test_list_cuddled_to_its_paragraph_is_a_list(self):
        html = self.body("Text\n- a\n- b\n")
        self.assertIn("<p>Text</p>", html)
        self.assertIn("<li>a</li>", html)

    def test_fence_inside_a_list_item_is_a_code_block(self):
        html = self.body("- a\n\n  ```py\n  x = 1\n  ```\n\n- b\n")
        self.assertIn('<pre><code class="py">x = 1</code></pre>', html)

    def test_fenced_block_carries_the_bare_language(self):
        html = self.body("```mermaid\ngraph TD\n```\n")
        self.assertIn('<pre><code class="mermaid">', html)
        self.assertNotIn("highlight", html)
        self.assertNotIn("language-", html)

    def test_the_engine_is_reset_between_documents(self):
        first = self.body("[a]: https://a.test\n\n[a]\n")
        second = self.body("[a]\n")
        self.assertIn("https://a.test", first)
        self.assertNotIn("https://a.test", second)
