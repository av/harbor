"""Unit tests for MiniMax auto-configuration in boost config."""

import os
import sys
import unittest
from unittest.mock import patch

# Add the boost src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestMiniMaxAutoConfig(unittest.TestCase):
    """Test that MiniMax backend is auto-registered when API key is set."""

    def _reload_config(self):
        """Reload the config module to pick up env var changes."""
        if 'config' in sys.modules:
            del sys.modules['config']
        import config
        return config

    @patch.dict(os.environ, {'HARBOR_MINIMAX_API_KEY': 'sk-test-minimax-key'}, clear=False)
    def test_minimax_api_registered_when_key_set(self):
        config = self._reload_config()

        self.assertIn('https://api.minimax.io/v1', config.BOOST_APIS)
        self.assertIn('sk-test-minimax-key', config.BOOST_KEYS)

    @patch.dict(os.environ, {'HARBOR_MINIMAX_API_KEY': ''}, clear=False)
    def test_minimax_api_not_registered_when_key_empty(self):
        config = self._reload_config()

        self.assertNotIn('https://api.minimax.io/v1', config.BOOST_APIS)

    @patch.dict(os.environ, {}, clear=False)
    def test_minimax_api_not_registered_when_key_missing(self):
        env = os.environ.copy()
        env.pop('HARBOR_MINIMAX_API_KEY', None)
        with patch.dict(os.environ, env, clear=True):
            config = self._reload_config()
            self.assertNotIn('https://api.minimax.io/v1', config.BOOST_APIS)

    @patch.dict(os.environ, {'HARBOR_MINIMAX_API_KEY': 'sk-test-key'}, clear=False)
    def test_minimax_apis_and_keys_aligned(self):
        config = self._reload_config()

        minimax_url = 'https://api.minimax.io/v1'
        if minimax_url in config.BOOST_APIS:
            idx = config.BOOST_APIS.index(minimax_url)
            self.assertEqual(config.BOOST_KEYS[idx], 'sk-test-key')

    @patch.dict(os.environ, {'HARBOR_MINIMAX_API_KEY': 'sk-test-key'}, clear=False)
    def test_minimax_config_object_value(self):
        config = self._reload_config()

        self.assertEqual(config.HARBOR_MINIMAX_API_KEY.value, 'sk-test-key')
        self.assertEqual(config.HARBOR_MINIMAX_API_KEY.name, 'HARBOR_MINIMAX_API_KEY')

    @patch.dict(os.environ, {'HARBOR_MINIMAX_API_KEY': 'sk-test-key'}, clear=False)
    def test_minimax_static_models_populated(self):
        config = self._reload_config()

        model_ids = [m['id'] for m in config.MINIMAX_MODELS]
        self.assertIn('MiniMax-M2.5', model_ids)
        self.assertIn('MiniMax-M2.5-highspeed', model_ids)

    @patch.dict(os.environ, {'HARBOR_MINIMAX_API_KEY': ''}, clear=False)
    def test_minimax_static_models_empty_when_no_key(self):
        config = self._reload_config()

        self.assertEqual(config.MINIMAX_MODELS, [])

    @patch.dict(os.environ, {'HARBOR_MINIMAX_API_KEY': 'sk-test-key'}, clear=False)
    def test_minimax_base_url_constant(self):
        config = self._reload_config()

        self.assertEqual(config.MINIMAX_BASE_URL, 'https://api.minimax.io/v1')


if __name__ == '__main__':
    unittest.main()
