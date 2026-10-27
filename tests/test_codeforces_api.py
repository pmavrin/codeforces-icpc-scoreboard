import hashlib
import io
import json
import unittest
import urllib.error
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import codeforces_api as api
import server


DATA = {'status': 'OK', 'result': {'contest': {'id': 727989, 'name': 'Example', 'phase': 'CODING'}, 'problems': [], 'rows': []}}
CONFIG = {'codeforces_bot_api_key': 'BOT_KEY', 'codeforces_bot_api_secret': 'BOT_SECRET'}


class Response(io.BytesIO):
    def __init__(self, data, status=200):
        super().__init__(data if isinstance(data, bytes) else json.dumps(data).encode())
        self.code = status


class CodeforcesAPITests(unittest.TestCase):
    def setUp(self):
        api._cache.clear()
        api._next_call = 0

    def test_targets(self):
        for value, group, expected in [
            ('2045', '', ('2045', '')),
            ('727989', 'Group42', ('727989', 'Group42')),
            ('https://codeforces.com/group/Group42/contest/727989/standings', '', ('727989', 'Group42')),
            ('https://codeforces.com/gym/100001?locale=en', '', ('100001', '')),
        ]:
            self.assertEqual(api.contest_target(value, group), expected)
        for value, group in [('0', ''), ('https://evil.example/contest/2045', ''),
                             ('https://codeforces.com@evil.example/contest/2045', ''),
                             ('https://codeforces.com/spectator/ranklist/abc', ''),
                             ('https://codeforces.com/group/ABC/contest/42', 'XYZ'), ('42', 'A&apiKey=bad')]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                api.contest_target(value, group)

    def test_signature_matches_documented_algorithm(self):
        with patch.object(api.secrets, 'token_hex', return_value='123abc'), patch.object(api.time, 'time', return_value=123456):
            url = api.signed_url({'contestId': '727989', 'groupCode': 'Group42'}, 'BOT_KEY', 'BOT_SECRET')
        params = parse_qs(urlsplit(url).query)
        expected = hashlib.sha512(b'123abc/contest.standings?apiKey=BOT_KEY&contestId=727989&groupCode=Group42&time=123456#BOT_SECRET').hexdigest()
        self.assertEqual(params['apiSig'], ['123abc' + expected])
        self.assertNotIn('BOT_SECRET', url)

    def test_regular_public_contest_is_anonymous(self):
        with patch.object(api, 'api_request', return_value=DATA) as fetch:
            self.assertEqual(api.fetch_standings(CONFIG, {'contestId': ['2045']})[0], 200)
        fetch.assert_called_once_with({'contestId': '2045'})

    def test_any_authorized_group_uses_server_key_without_manager_mode(self):
        for group in ['Group42', 'OtherGroup']:
            with patch.object(api, 'api_request', return_value=DATA) as fetch:
                status, _ = api.fetch_standings(CONFIG, {'contestId': ['727989'], 'groupCode': [group], 'apiKey': ['ATTACKER'], 'api_secret': ['ATTACKER'], 'asManager': ['true'], 'method': ['contest.status']})
            self.assertEqual(status, 200)
            fetch.assert_called_once_with({'contestId': '727989', 'groupCode': group, 'showUnofficial': 'true'}, 'BOT_KEY', 'BOT_SECRET')

    def test_gym_falls_back_to_bot(self):
        with patch.object(api, 'api_request', side_effect=[api.APIError(403, 'Needs auth', True), DATA]) as fetch:
            self.assertEqual(api.fetch_standings(CONFIG, {'url': ['https://codeforces.com/gym/100001']})[0], 200)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args.args[1:], ('BOT_KEY', 'BOT_SECRET'))

    def test_missing_bot_key_and_old_personal_keys_are_not_used(self):
        with patch.object(api, 'api_request') as fetch:
            status, data = api.fetch_standings({'api_key': 'OLD_KEY', 'api_secret': 'OLD_SECRET'}, {'contestId': ['727989'], 'groupCode': ['ABC']})
        self.assertEqual(status, 503)
        self.assertIn('CODEFORCES_API_KEY', data['comment'])
        fetch.assert_not_called()

    def test_request_overrides_default_group(self):
        with patch.object(api, 'api_request', return_value=DATA) as fetch:
            api.fetch_standings({**CONFIG, 'group_code': 'Private'}, {'contestId': ['2045']})
        fetch.assert_called_once_with({'contestId': '2045'})

    def test_cache_is_bounded_shared_and_credentials_sensitive(self):
        query = {'contestId': ['727989'], 'groupCode': ['ABC']}
        with patch.object(api, 'api_request', return_value=DATA) as fetch:
            api.fetch_standings(CONFIG, query)
            api.fetch_standings(CONFIG, query)
            self.assertEqual(fetch.call_count, 1)
            api.fetch_standings({**CONFIG, 'codeforces_bot_api_secret': 'ROTATED'}, query)
            self.assertEqual(fetch.call_count, 2)
            for i in range(40):
                api.fetch_standings(CONFIG, {'contestId': [str(i + 1)]})
            self.assertLessEqual(len(api._cache), 32)
        self.assertNotIn('BOT_KEY', repr(api._cache.keys()))

    def test_busy_requests_do_not_queue(self):
        with api._lock, patch.object(api, 'api_request') as fetch:
            self.assertEqual(api.fetch_standings(CONFIG, {'contestId': ['2045']})[0], 429)
            fetch.assert_not_called()

    def test_upstream_response_and_signed_url_are_never_echoed_on_error(self):
        payload = {'status': 'FAILED', 'comment': 'apiKey: BOT_KEY invalid; apiSig=SECRET_SIGNATURE'}
        with patch.object(api._opener, 'open', return_value=Response(payload, 400)):
            with self.assertRaises(api.APIError) as error:
                api.api_request({'contestId': '727989'}, 'BOT_KEY', 'BOT_SECRET')
        self.assertEqual(error.exception.status, 503)
        self.assertNotIn('BOT_KEY', str(error.exception))
        self.assertNotIn('SECRET_SIGNATURE', str(error.exception))
        api._next_call = 0
        with patch.object(api._opener, 'open', side_effect=urllib.error.URLError('https://codeforces.com/api/?apiKey=BOT_KEY')):
            with self.assertRaises(api.APIError) as error:
                api.api_request({'contestId': '727989'}, 'BOT_KEY', 'BOT_SECRET')
        self.assertNotIn('BOT_KEY', str(error.exception))

    def test_access_denied_non_json_and_redirects(self):
        for response, expected in [(Response({'status': 'FAILED', 'comment': 'contestId: Contest not found'}, 400), 403),
                                   (Response(b'<html>Cloudflare</html>', 403), 502),
                                   (Response(b'', 302), 502), (Response(b'', 429), 429)]:
            api._next_call = 0
            with patch.object(api._opener, 'open', return_value=response), self.assertRaises(api.APIError) as error:
                api.api_request({'contestId': '42'})
            self.assertEqual(error.exception.status, expected)
        self.assertIsNone(api.NoRedirects().redirect_request(None, None, 302, '', {}, 'https://evil.example'))

    def test_global_api_spacing(self):
        api._next_call = 12.1
        with patch.object(api.time, 'monotonic', return_value=10), patch.object(api.time, 'sleep') as sleep, \
                patch.object(api._opener, 'open', return_value=Response(DATA)):
            self.assertEqual(api.api_request({'contestId': '2045'}), DATA)
        self.assertAlmostEqual(sleep.call_args.args[0], 2.1)

    def test_environment_and_public_config(self):
        with patch.dict(server.os.environ, {'CODEFORCES_API_KEY': 'BOT_KEY', 'CODEFORCES_API_SECRET': 'BOT_SECRET'}, clear=True), patch.object(server, 'CONFIG_PATH') as path:
            path.exists.return_value = False
            config = server.load_raw_config()
        self.assertEqual(config['codeforces_bot_api_key'], 'BOT_KEY')
        public = json.dumps(server.app_public_config(config))
        self.assertNotIn('BOT_KEY', public)
        self.assertNotIn('BOT_SECRET', public)
        self.assertIn('pashka-bot', public)


if __name__ == '__main__':
    unittest.main()
