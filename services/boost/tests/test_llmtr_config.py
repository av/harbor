"""Unit tests for LLMTR auto-configuration in boost config."""

import os
import sys
import unittest
from unittest.mock import patch

# Add the boost src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

LLMTR_URL = 'https://llmtr.com/v1'


class TestLLMTRAutoConfig(unittest.TestCase):
    """Test that the LLMTR backend is auto-registered when the API key is set."""

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

    @patch.dict(os.environ, {'HARBOR_LLMTR_API_KEY': 'sk-test-llmtr-key'}, clear=False)
    def test_llmtr_api_registered_when_key_set(self):
        config = self._reload_config()

        self.assertIn(LLMTR_URL, config.BOOST_APIS)
        self.assertIn('sk-test-llmtr-key', config.BOOST_KEYS)

    @patch.dict(os.environ, {'HARBOR_LLMTR_API_KEY': ''}, clear=False)
    def test_llmtr_api_not_registered_when_key_empty(self):
        config = self._reload_config()

        self.assertNotIn(LLMTR_URL, config.BOOST_APIS)

    def test_llmtr_api_not_registered_when_key_missing(self):
        env = os.environ.copy()
        env.pop('HARBOR_LLMTR_API_KEY', None)
        with patch.dict(os.environ, env, clear=True):
            config = self._reload_config()
            self.assertNotIn(LLMTR_URL, config.BOOST_APIS)

    @patch.dict(os.environ, {
        'HARBOR_LLMTR_API_KEY': 'sk-llmtr',
        'HARBOR_MINIMAX_API_KEY': 'sk-minimax',
    }, clear=False)
    def test_llmtr_key_aligned_with_url_next_to_minimax(self):
        config = self._reload_config()

        idx = config.BOOST_APIS.index(LLMTR_URL)
        self.assertEqual(config.BOOST_KEYS[idx], 'sk-llmtr')
        idx = config.BOOST_APIS.index('https://api.minimax.io/v1')
        self.assertEqual(config.BOOST_KEYS[idx], 'sk-minimax')

    @patch.dict(os.environ, {'HARBOR_LLMTR_API_KEY': 'sk-test-key'}, clear=False)
    def test_llmtr_config_object_value(self):
        config = self._reload_config()

        self.assertEqual(config.HARBOR_LLMTR_API_KEY.value, 'sk-test-key')
        self.assertEqual(config.HARBOR_LLMTR_API_KEY.name, 'HARBOR_LLMTR_API_KEY')

    def test_llmtr_base_url_constant(self):
        config = self._reload_config()

        self.assertEqual(config.LLMTR_BASE_URL, LLMTR_URL)


if __name__ == '__main__':
    unittest.main()
