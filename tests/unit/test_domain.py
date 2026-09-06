import unittest

from MarkdownGlance.preview.domain.contracts import AssetKey, AssetKind, RenderSettings
from MarkdownGlance.preview.domain.settings import parse_settings


class DomainTest(unittest.TestCase):
    def test_asset_safe_label_never_contains_locator(self):
        locator = "https://example.test/private/secret.png?token=top-secret"
        label = AssetKey(AssetKind.REMOTE_IMAGE, locator).safe_label
        self.assertEqual(label.split(":")[:2], ["remote_image", "example.test"])
        self.assertNotIn("secret", label)
        self.assertNotIn("token", label)

    def test_mermaid_label_contains_host_not_source_path(self):
        locator = "https://mermaid.test/img/encoded-private-diagram"
        label = AssetKey(AssetKind.MERMAID, locator).safe_label
        self.assertIn("mermaid.test", label)
        self.assertNotIn("encoded-private-diagram", label)

    def test_math_label_contains_host_not_formula(self):
        locator = "https://math.test/png.image?%5Cdpi%7B230%7Dsecret%5E2"
        label = AssetKey(AssetKind.MATH, locator).safe_label
        self.assertIn("math.test", label)
        self.assertNotIn("secret", label)

    def test_math_is_opt_in_and_its_server_must_be_https(self):
        self.assertFalse(RenderSettings().enable_math)
        self.assertEqual(RenderSettings().math_server, "https://latex.codecogs.com")
        warnings = []
        settings = parse_settings(
            {"enable_math": True, "math_server": "https://math.test/"}, warnings.append
        )
        self.assertTrue(settings.enable_math)
        self.assertEqual(settings.math_server, "https://math.test")
        self.assertEqual(warnings, [])
        settings = parse_settings(
            {"enable_math": "yes", "math_server": "http://math.test"}, warnings.append
        )
        self.assertFalse(settings.enable_math)
        self.assertEqual(settings.math_server, "https://latex.codecogs.com")
        self.assertEqual(len(warnings), 2)

    def test_settings_validate_types_and_clamp_ranges(self):
        warnings = []
        settings = parse_settings(
            {
                "update_delay_ms": 99999,
                "enable_mermaid": "yes",
                "mermaid_server": "http://unsafe.test",
                "remote_max_dimension": 1,
            },
            warnings.append,
        )
        self.assertEqual(settings.update_delay_ms, 5000)
        self.assertFalse(settings.enable_mermaid)
        self.assertEqual(settings.mermaid_server, "https://mermaid.ink")
        self.assertEqual(settings.remote_max_dimension, 16)
        self.assertEqual(len(warnings), 2)

    def test_toc_is_opt_in_and_switched_on_by_a_boolean(self):
        self.assertFalse(RenderSettings().enable_toc)
        self.assertTrue(parse_settings({"enable_toc": True}).enable_toc)
        warnings = []
        self.assertFalse(parse_settings({"enable_toc": "on"}, warnings.append).enable_toc)
        self.assertEqual(len(warnings), 1)

    def test_auto_width_is_on_and_switched_off_by_a_boolean(self):
        self.assertTrue(RenderSettings().auto_width)
        self.assertFalse(parse_settings({"auto_width": False}).auto_width)
        warnings = []
        self.assertTrue(parse_settings({"auto_width": 0.5}, warnings.append).auto_width)
        self.assertEqual(len(warnings), 1)

    def test_settings_are_frozen(self):
        with self.assertRaises(Exception):
            RenderSettings().update_delay_ms = 1
