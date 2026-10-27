import json
import re
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import server
from codeforces import parse_codeforces_standings, spectator_url


URL = 'https://codeforces.com/spectator/ranklist/example-token'
FIXTURE = Path(__file__).parent / 'fixtures' / 'codeforces-spectator.html'


class CodeforcesTests(unittest.TestCase):
    def setUp(self):
        self.page = FIXTURE.read_text()

    def parse(self, page=None, url=URL):
        return parse_codeforces_standings(self.page if page is None else page, url)['result']

    def test_spectator_html(self):
        result = self.parse()
        self.assertEqual(result['contest']['name'], 'Example & Contest')
        self.assertEqual(result['contest']['remainingTimeSeconds'], 16362)
        self.assertIsNone(result['contest']['startTimeSeconds'])
        self.assertEqual([p['index'] for p in result['problems']], list('ABCD'))
        self.assertEqual(len(result['rows']), 2)
        row, solo = result['rows']
        self.assertEqual(row['party']['teamName'], 'Team <One>')
        self.assertEqual(row['party']['members'], [{'handle': 'Legend'}, {'handle': 'Other'}])
        self.assertEqual((row['rank'], row['points'], row['penalty']), (1, 1, 135))
        self.assertEqual(row['problemResults'][0], {
            'points': 1, 'rejectedAttemptCount': 3, 'bestSubmissionTimeSeconds': 4500,
        })
        self.assertEqual(row['problemResults'][1]['rejectedAttemptCount'], 4)
        self.assertEqual(row['problemResults'][2], {'points': 0, 'rejectedAttemptCount': 0})
        self.assertEqual(solo['party']['teamName'], '')
        self.assertEqual(solo['party']['members'], [{'handle': 'Solo'}])

    def test_cells_zero_time_and_pending_notation(self):
        # Pending notation is synthetic: the supplied live snapshot was not frozen.
        page = self.page.replace('+3', '+').replace('01:15', '00:00').replace('-4', '?2')
        row = self.parse(page)['rows'][0]
        self.assertEqual(row['problemResults'][0]['bestSubmissionTimeSeconds'], 0)
        self.assertEqual(row['problemResults'][0]['rejectedAttemptCount'], 0)
        self.assertEqual(row['problemResults'][1], {
            'points': 0, 'rejectedAttemptCount': 0, 'frozen': True, 'pendingAttemptCount': 2,
        })
        self.assertEqual(self.parse(page.replace('?2', '?'))['rows'][0]['problemResults'][1]['pendingAttemptCount'], 0)

    def test_stable_identity_on_reordering_rename_and_url_parameters(self):
        rows = re.findall(r'<tr participantId=.*?</tr>', self.page, re.S)
        swapped = self.page.replace(rows[0], 'PLACEHOLDER').replace(rows[1], rows[0]).replace('PLACEHOLDER', rows[1])
        before = self.parse()['rows']
        after = self.parse(swapped, URL + '?locale=en#p101')['rows']
        self.assertEqual(before[0]['party']['teamId'], after[1]['party']['teamId'])
        self.assertEqual(before[0]['party']['teamId'], self.parse(self.page.replace('Team &lt;One&gt;', 'Renamed'))['rows'][0]['party']['teamId'])
        self.assertNotEqual(before[0]['party']['teamId'], self.parse(url=URL + '-other')['rows'][0]['party']['teamId'])

    def test_empty_finished_and_upcoming(self):
        empty = re.sub(r'<tr participantId=.*?</tr>', '', self.page, flags=re.S)
        self.assertEqual(self.parse(empty)['rows'], [])
        finished = self.parse(self.page.replace('Contest is running', 'Contest is over'))['contest']
        self.assertEqual(finished['phase'], 'FINISHED')
        self.assertNotIn('remainingTimeSeconds', finished)
        upcoming = self.parse(self.page.replace('Contest is running', 'Contest has not started'))['contest']
        self.assertEqual(upcoming['phase'], 'BEFORE')

    def test_unofficial(self):
        row = self.parse(self.page.replace('<td>1</td>\n', '<td>*</td>\n', 1))['rows'][0]
        self.assertEqual(row['party']['participantType'], 'OUT_OF_COMPETITION')

    def test_invalid_html_and_unsupported_scoring_fail_loudly(self):
        for page in ['<title>Just a moment...</title>', self.page.replace('<th>=</th>', '<th>Points</th>'),
                     self.page.replace('01:15', 'invalid'), self.page.replace('problemId="11"', '', 1),
                     self.page.replace('problemId="11"', 'problemId="99"', 1),
                     self.page.replace('<span class="cell-time">01:15</span>', ''),
                     self.page.replace('+3', '100')]:
            with self.subTest(page=page[:60]), self.assertRaises(ValueError):
                self.parse(page)

    def test_url_validation(self):
        for value in ['2045', 'https://codeforces.com/contest/2045', 'file:///tmp/page.html',
                      'https://evil.example/spectator/ranklist/abc',
                      'https://codeforces.com.evil.example/spectator/ranklist/abc',
                      'https://user:pass@codeforces.com/spectator/ranklist/abc',
                      URL + '/edit', URL.replace('.com/', '.com:8080/')]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                spectator_url(value)
        self.assertEqual(spectator_url(URL + '/?locale=en#p101'), URL)

    def test_adapter_fetches_html_without_credentials(self):
        config = {'codeforces_url': URL, 'api_key': 'unused', 'api_secret': 'unused'}
        with patch.object(server, 'read_public_html', return_value=self.page) as fetch:
            status, content_type, body = server.fetch_codeforces_standings(config, {})
        fetch.assert_called_once_with(URL)
        self.assertEqual(status, 200)
        self.assertIn('application/json', content_type)
        self.assertEqual(len(json.loads(body)['result']['rows']), 2)
        self.assertEqual(server.fetch_codeforces_standings({}, {'contestId': ['2045']})[0], 400)

    def test_cloudflare_error_is_json_and_actionable(self):
        with patch.object(server, 'read_public_html', side_effect=urllib.error.HTTPError(URL, 403, 'Forbidden', {}, None)):
            status, _, body = server.fetch_codeforces_standings({'codeforces_url': URL}, {})
        self.assertEqual(status, 403)
        self.assertIn('Cloudflare', json.loads(body)['comment'])

    def test_source_configuration(self):
        with patch.object(server, 'load_raw_config', return_value={'source': 'domjudge', 'university_aliases': {'University': 'U'}}):
            config = server.load_request_config({'source': ['codeforces'], 'url': [URL]})
        self.assertEqual(config['codeforces_url'], URL)
        self.assertEqual(server.app_public_config(config)['standingsUrl'], URL)
        self.assertEqual(server.app_public_config(config)['universityAliases'], {'University': 'U'})


if __name__ == '__main__':
    unittest.main()
