import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ffdc_config import env_float, env_int, env_path, env_url


class ConfigurationTests(unittest.TestCase):
    def test_invalid_integer_uses_default_and_bounds_are_applied(self):
        with patch.dict(os.environ, {"FFDC_TEST_INT": "not-a-number"}, clear=False):
            self.assertEqual(env_int("FFDC_TEST_INT", 4, minimum=1), 4)
        with patch.dict(os.environ, {"FFDC_TEST_INT": "999"}, clear=False):
            self.assertEqual(env_int("FFDC_TEST_INT", 4, minimum=1, maximum=10), 10)

    def test_float_fallback_and_lower_bound(self):
        with patch.dict(os.environ, {"FFDC_TEST_FLOAT": "-2.5"}, clear=False):
            self.assertEqual(env_float("FFDC_TEST_FLOAT", 0.5, minimum=0.0), 0.0)
        with patch.dict(os.environ, {"FFDC_TEST_FLOAT": "bad"}, clear=False):
            self.assertEqual(env_float("FFDC_TEST_FLOAT", 0.5), 0.5)

    def test_path_and_url_normalization(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"FFDC_TEST_PATH": directory, "FFDC_TEST_URL": "https://example.test///"}, clear=False):
                self.assertEqual(env_path("FFDC_TEST_PATH", "/fallback"), Path(directory))
                self.assertEqual(env_url("FFDC_TEST_URL", "https://fallback.test"), "https://example.test")


if __name__ == "__main__":
    unittest.main()
