"""Integration tests for MiniMax via boost's OpenAI-compatible proxy.

Requires MINIMAX_API_KEY environment variable to be set.
"""

import os
import sys
import json
import unittest
import urllib.request
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

MINIMAX_API_KEY = os.environ.get('MINIMAX_API_KEY', '')
MINIMAX_BASE_URL = 'https://api.minimax.io/v1'


@unittest.skipUnless(MINIMAX_API_KEY, 'MINIMAX_API_KEY not set')
class TestMiniMaxIntegration(unittest.TestCase):
    """Integration tests verifying MiniMax API connectivity."""

    def test_chat_completion_m25(self):
        body = json.dumps({
            'model': 'MiniMax-M2.5',
            'messages': [{'role': 'user', 'content': 'Say hello in one word.'}],
            'max_tokens': 20,
            'temperature': 1.0,
        }).encode()
        req = urllib.request.Request(
            f'{MINIMAX_BASE_URL}/chat/completions',
            data=body,
            headers={
                'Authorization': f'Bearer {MINIMAX_API_KEY}',
                'Content-Type': 'application/json',
            },
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=60).read())
        content = resp['choices'][0]['message']['content']
        self.assertTrue(len(content) > 0)

    def test_chat_completion_m25_highspeed(self):
        body = json.dumps({
            'model': 'MiniMax-M2.5-highspeed',
            'messages': [{'role': 'user', 'content': 'Say hi in one word.'}],
            'max_tokens': 20,
            'temperature': 1.0,
        }).encode()
        req = urllib.request.Request(
            f'{MINIMAX_BASE_URL}/chat/completions',
            data=body,
            headers={
                'Authorization': f'Bearer {MINIMAX_API_KEY}',
                'Content-Type': 'application/json',
            },
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
        content = resp['choices'][0]['message']['content']
        self.assertTrue(len(content) > 0)

    def test_boost_auto_registers_minimax(self):
        env = os.environ.copy()
        env['HARBOR_MINIMAX_API_KEY'] = MINIMAX_API_KEY
        with patch.dict(os.environ, env, clear=True):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config

            self.assertIn(MINIMAX_BASE_URL, config.BOOST_APIS)
            model_ids = [m['id'] for m in config.MINIMAX_MODELS]
            self.assertIn('MiniMax-M2.5', model_ids)
            self.assertIn('MiniMax-M2.5-highspeed', model_ids)


if __name__ == '__main__':
    unittest.main()
