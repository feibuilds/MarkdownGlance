import unittest
from unittest import mock

from MarkdownGlance.preview.application import render_pipeline
from MarkdownGlance.preview.application.errors import RenderFailure, describe
from MarkdownGlance.preview.domain.contracts import DiagnosticStage
from MarkdownGlance.preview.renderer import markdown_engine
from MarkdownGlance.preview.renderer.errors import ERROR_NOTE, error_card
from MarkdownGlance.tests.unit.test_renderer import request


class BrokenEngine:
    """What a library that fails to import looks like from the pipeline."""

    def convert(self, source):
        raise ModuleNotFoundError("No module named 'pymdownx.superfences'")


class QuietResolver:
    def resolve(self, keys, session_id):
        return {}


class BrokenResolver:
    def resolve(self, keys, session_id):
        raise RuntimeError("cache is gone")


class RenderPipelineTest(unittest.TestCase):
    """Issue #5: every failure used to be "Serialise / Render failed"."""

    def test_a_document_renders_through_the_pipeline(self):
        document = render_pipeline.render(request("# Test\n\nHello.\n"), QuietResolver())
        self.assertIn("<h1", document.body_html)

    def test_a_parser_failure_names_the_parse_stage_and_the_exception(self):
        with mock.patch.object(markdown_engine, "_default", BrokenEngine()):
            with self.assertRaises(RenderFailure) as caught:
                render_pipeline.render(request("# Test\n"), QuietResolver())
        failure = caught.exception
        self.assertEqual(failure.stage, DiagnosticStage.PARSE)
        self.assertEqual(
            failure.safe_message,
            "ModuleNotFoundError: No module named 'pymdownx.superfences'",
        )
        self.assertIsInstance(failure.cause, ModuleNotFoundError)
        self.assertIs(failure.__cause__, failure.cause)

    def test_a_resolver_failure_names_the_asset_stage(self):
        with self.assertRaises(RenderFailure) as caught:
            render_pipeline.render(request("![x](a.png)\n"), BrokenResolver())
        self.assertEqual(caught.exception.stage, DiagnosticStage.ASSET)
        self.assertEqual(caught.exception.safe_message, "RuntimeError: cache is gone")

    def test_a_serialiser_failure_names_the_serialise_stage(self):
        with mock.patch.object(
            render_pipeline, "serialise", side_effect=KeyError("alt")
        ):
            with self.assertRaises(RenderFailure) as caught:
                render_pipeline.render(request("# Test\n"), QuietResolver())
        self.assertEqual(caught.exception.stage, DiagnosticStage.SERIALISE)
        self.assertEqual(caught.exception.safe_message, "KeyError: 'alt'")

    def test_describe_is_the_class_and_the_message(self):
        self.assertEqual(describe(ValueError("bad")), "ValueError: bad")
        self.assertEqual(describe(ValueError()), "ValueError")
        self.assertEqual(describe(ValueError("  ")), "ValueError")

    def test_the_card_carries_the_stage_the_message_and_where_the_rest_is(self):
        html = error_card(DiagnosticStage.PARSE, "ModuleNotFoundError: No module named 'x'")
        self.assertIn("<strong>Parse</strong>", html)
        self.assertIn("ModuleNotFoundError: No module named &#x27;x&#x27;", html)
        self.assertIn(ERROR_NOTE.replace(">", "&gt;"), html)


if __name__ == "__main__":
    unittest.main()
