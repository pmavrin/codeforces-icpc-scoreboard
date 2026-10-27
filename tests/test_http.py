import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import urlencode

import server


FIXTURES = Path(__file__).parent / 'fixtures'
URL = 'https://codeforces.com/spectator/ranklist/example-token'


class HTTPRouteTests(unittest.TestCase):
    def request(self, path):
        handler = object.__new__(server.ScoreboardHandler)
        handler.path = path
        handler.send_bytes = Mock()
        handler.do_GET()
        return handler.send_bytes.call_args.args

    def test_page_and_data_for_spectator_link(self):
        query = urlencode({'source': 'codeforces', 'url': URL})
        with patch.object(server, 'load_raw_config', return_value={}):
            status, _, page, _ = self.request('/?' + query)
            self.assertEqual(status, 200)
            self.assertIn(b'Spectator ranklist URL', page)
            self.assertIn(URL.encode(), page)
            self.assertNotIn(b'id="apiKeyInput"', page)
            with patch.object(server, 'read_public_html', return_value=(FIXTURES / 'codeforces-spectator.html').read_text()):
                status, _, body, _ = self.request('/api/standings?' + query)
            self.assertEqual(status, 200)
            self.assertEqual(len(json.loads(body)['result']['rows']), 2)

    def test_domjudge_route_still_works(self):
        with patch.object(server, 'load_raw_config', return_value={}), \
                patch.object(server, 'read_public_html', return_value=(FIXTURES / 'domjudge-modern.html').read_text()):
            status, _, body, _ = self.request('/api/standings?source=domjudge&url=https://judge.example/public')
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)['result']['rows']), 2)

    def test_cloudflare_and_legacy_contest_links(self):
        with patch.object(server, 'load_raw_config', return_value={}):
            status, _, body, _ = self.request('/api/standings?source=codeforces&contestId=2045')
            self.assertEqual(status, 400)
            self.assertIn('spectator', json.loads(body)['comment'])
            with patch.object(server, 'read_public_html', side_effect=HTTPError(URL, 403, 'Forbidden', {}, None)):
                status, _, body, _ = self.request('/api/standings?' + urlencode({'source': 'codeforces', 'url': URL}))
            self.assertEqual(status, 403)
            self.assertIn('Cloudflare', json.loads(body)['comment'])


if __name__ == '__main__':
    unittest.main()
