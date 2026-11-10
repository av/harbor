"""Integration tests for UberLLM via boost's OpenAI-compatible proxy.

Requires UBERLLM_API_KEY environment variable to be set.
"""

import os
import sys
import json
import unittest
import urllib.request
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

UBERLLM_API_KEY = os.environ.get('UBERLLM_API_KEY', '')
UBERLLM_BASE_URL = 'https://api.uberllm.dev/v1'


@unittest.skipUnless(UBERLLM_API_KEY, 'UBERLLM_API_KEY not set')
class TestUberLLMIntegration(unittest.TestCase):
    """Integration tests verifying UberLLM API connectivity."""

    def _get(self, path):
        req = urllib.request.Request(
            f'{UBERLLM_BASE_URL}{path}',
            headers={'Authorization': f'Bearer {UBERLLM_API_KEY}'},
        )
        return json.loads(urllib.request.urlopen(req, timeout=30).read())

    def test_models_endpoint_lists_models(self):
        # Boost discovers backend models through /models, so this must work.
        model_ids = [m['id'] for m in self._get('/models')['data']]
        self.assertIn('deepseek/deepseek-v4.1-flash', model_ids)

    def test_chat_completion(self):
        body = json.dumps({
            'model': 'deepseek/deepseek-v4.1-flash',
            'messages': [{'role': 'user', 'content': 'Say hello in one word.'}],
            'max_tokens': 20,
        }).encode()
        req = urllib.request.Request(
            f'{UBERLLM_BASE_URL}/chat/completions',
            data=body,
            headers={
                'Authorization': f'Bearer {UBERLLM_API_KEY}',
                'Content-Type': 'application/json',
            },
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=60).read())
        content = resp['choices'][0]['message']['content']
        self.assertTrue(len(content) > 0)

    def test_boost_auto_registers_uberllm(self):
        env = os.environ.copy()
        env['HARBOR_UBERLLM_API_KEY'] = UBERLLM_API_KEY
        with patch.dict(os.environ, env, clear=True):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config

            self.assertIn(UBERLLM_BASE_URL, config.BOOST_APIS)


if __name__ == '__main__':
    unittest.main()
