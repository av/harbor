"""Unit tests for UberLLM auto-configuration in boost config."""

import os
import sys
import unittest
from unittest.mock import patch

# Add the boost src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

UBERLLM_URL = 'https://api.uberllm.dev/v1'


class TestUberLLMAutoConfig(unittest.TestCase):
    """Test that the UberLLM backend is auto-registered when the API key is set."""

    def setUp(self):
        # _reload_config() replaces sys.modules['config']; restore it so other
        # modules (e.g. auth.py) don't keep a stale reference.
        self._orig_config = sys.modules.get('config')

    def tearDown(self):
        if self._orig_config is not None:
            sys.modules['config'] = self._orig_config

    def _reload_config(self):
        """Reload the config module to pick up env var changes."""
        if 'config' in sys.modules:
            del sys.modules['config']
        import config
        return config

    @patch.dict(os.environ, {'HARBOR_UBERLLM_API_KEY': 'sk-test-uberllm-key'}, clear=False)
    def test_uberllm_api_registered_when_key_set(self):
        config = self._reload_config()

        self.assertIn(UBERLLM_URL, config.BOOST_APIS)
        self.assertIn('sk-test-uberllm-key', config.BOOST_KEYS)

    @patch.dict(os.environ, {'HARBOR_UBERLLM_API_KEY': ''}, clear=False)
    def test_uberllm_api_not_registered_when_key_empty(self):
        config = self._reload_config()

        self.assertNotIn(UBERLLM_URL, config.BOOST_APIS)

    def test_uberllm_api_not_registered_when_key_missing(self):
        env = os.environ.copy()
        env.pop('HARBOR_UBERLLM_API_KEY', None)
        with patch.dict(os.environ, env, clear=True):
            config = self._reload_config()
            self.assertNotIn(UBERLLM_URL, config.BOOST_APIS)

    @patch.dict(os.environ, {
        'HARBOR_UBERLLM_API_KEY': 'sk-uberllm',
        'HARBOR_MINIMAX_API_KEY': 'sk-minimax',
    }, clear=False)
    def test_uberllm_key_aligned_with_url_next_to_minimax(self):
        config = self._reload_config()

        idx = config.BOOST_APIS.index(UBERLLM_URL)
        self.assertEqual(config.BOOST_KEYS[idx], 'sk-uberllm')
        idx = config.BOOST_APIS.index('https://api.minimax.io/v1')
        self.assertEqual(config.BOOST_KEYS[idx], 'sk-minimax')

    @patch.dict(os.environ, {'HARBOR_UBERLLM_API_KEY': 'sk-test-key'}, clear=False)
    def test_uberllm_config_object_value(self):
        config = self._reload_config()

        self.assertEqual(config.HARBOR_UBERLLM_API_KEY.value, 'sk-test-key')
        self.assertEqual(config.HARBOR_UBERLLM_API_KEY.name, 'HARBOR_UBERLLM_API_KEY')

    def test_uberllm_base_url_constant(self):
        config = self._reload_config()

        self.assertEqual(config.UBERLLM_BASE_URL, UBERLLM_URL)


if __name__ == '__main__':
    unittest.main()
