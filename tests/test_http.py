import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlencode

import server
import codeforces_api


FIXTURES = Path(__file__).parent / 'fixtures'
URL = 'https://codeforces.com/group/Group42/contest/727989'
CONFIG = {'codeforces_bot_api_key': 'BOT_KEY', 'codeforces_bot_api_secret': 'BOT_SECRET'}
DATA = {'status': 'OK', 'result': {'contest': {'id': 727989}, 'problems': [], 'rows': []}}


class HTTPRouteTests(unittest.TestCase):
    def setUp(self):
        codeforces_api._cache.clear()

    def request(self, path):
        handler = object.__new__(server.ScoreboardHandler)
        handler.path = path
        handler.send_bytes = Mock()
        handler.do_GET()
        return handler.send_bytes.call_args.args

    def test_page_and_data_for_group_contest(self):
        query = urlencode({'source': 'codeforces', 'url': URL})
        with patch.object(server, 'load_raw_config', return_value=CONFIG):
            status, _, page, _ = self.request('/?' + query)
            self.assertEqual(status, 200)
            self.assertIn(b'Contest ID or URL', page)
            self.assertIn(URL.encode(), page)
            self.assertNotIn(b'id="apiKeyInput"', page)
            self.assertNotIn(b'BOT_KEY', page)
            self.assertNotIn(b'BOT_SECRET', page)
            with patch.object(codeforces_api, 'api_request', return_value=DATA):
                status, _, body, _ = self.request('/api/standings?' + query)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), DATA)

    def test_domjudge_route_still_works(self):
        with patch.object(server, 'load_raw_config', return_value={}), \
                patch.object(server, 'read_public_html', return_value=(FIXTURES / 'domjudge-modern.html').read_text()):
            status, _, body, _ = self.request('/api/standings?source=domjudge&url=https://judge.example/public')
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)['result']['rows']), 2)

    def test_bot_setup_and_access_errors(self):
        with patch.object(server, 'load_raw_config', return_value={}):
            status, _, body, _ = self.request('/api/standings?source=codeforces&contestId=727989&groupCode=Group42')
            self.assertEqual(status, 503)
            self.assertIn('CODEFORCES_API_KEY', json.loads(body)['comment'])
        with patch.object(server, 'load_raw_config', return_value=CONFIG):
            with patch.object(codeforces_api, 'api_request', side_effect=codeforces_api.APIError(403, 'pashka-bot cannot view this contest')):
                status, _, body, _ = self.request('/api/standings?' + urlencode({'source': 'codeforces', 'url': URL}))
            self.assertEqual(status, 403)
            self.assertIn('pashka-bot', json.loads(body)['comment'])


if __name__ == '__main__':
    unittest.main()
