import copy
import unittest
from unittest.mock import patch

import codeforces_api as api


def ghost_row(name='Ghost'):
    return {
        'rank': 1, 'points': 2, 'penalty': 190,
        'party': {'ghost': True, 'teamName': name, 'contestId': 106825,
                  'participantType': 'VIRTUAL', 'startTimeSeconds': 100},
        'problemResults': [
            {'points': 1, 'bestSubmissionTimeSeconds': 600, 'rejectedAttemptCount': 2, 'type': 'FINAL'},
            {'points': 1, 'bestSubmissionTimeSeconds': 7200, 'rejectedAttemptCount': 1,
             'type': 'FINAL', 'firstToSolve': True},
            {'points': 0, 'rejectedAttemptCount': 7, 'type': 'FINAL'},
        ],
    }


def standings(rows, **contest):
    return {'status': 'OK', 'result': {
        'contest': {'id': 733439, 'type': 'ICPC', 'phase': 'CODING', 'frozen': False,
                    'relativeTimeSeconds': 600, 'durationSeconds': 18000, **contest},
        'problems': [], 'rows': rows,
    }}


class GhostReplayTests(unittest.TestCase):
    def test_elapsed_time_reveals_only_past_solutions_and_recomputes_totals(self):
        ghost = ghost_row()
        original = copy.deepcopy(ghost)
        result = api.contest_standings(standings([ghost]), '733439', True)['result']['rows'][0]
        self.assertEqual((result['points'], result['penalty']), (1, 50))
        self.assertEqual(result['problemResults'][0], ghost['problemResults'][0])
        for problem in result['problemResults'][1:]:
            self.assertEqual(problem, {'points': 0, 'rejectedAttemptCount': 0, 'type': 'FINAL'})
        self.assertEqual(ghost, original)

    def test_solution_appears_at_its_timestamp_not_before(self):
        ghost = ghost_row()
        self.assertEqual(api.replay_ghost(ghost, 599)['points'], 0)
        self.assertEqual(api.replay_ghost(ghost, 600)['points'], 1)
        self.assertEqual(api.replay_ghost(ghost, 7199)['points'], 1)
        self.assertEqual(api.replay_ghost(ghost, 7200)['penalty'], 190)

    def test_live_teams_unchanged_and_sorted_against_current_ghost_scores(self):
        local = {'rank': 99, 'points': 1, 'penalty': 8,
                 'party': {'contestId': 733439, 'participantType': 'CONTESTANT', 'teamName': 'MIR'},
                 'problemResults': [{'points': 1, 'bestSubmissionTimeSeconds': 480, 'rejectedAttemptCount': 0}]}
        rows = api.contest_standings(standings([ghost_row('B'), ghost_row('A'), local]), '733439', True)['result']['rows']
        self.assertEqual([r['party']['teamName'] for r in rows], ['MIR', 'A', 'B'])
        self.assertEqual([r['rank'] for r in rows], [1, 2, 2])
        self.assertEqual(rows[0], {**local, 'rank': 1})

    def test_finished_contest_keeps_final_results_including_failed_attempts(self):
        data = standings([ghost_row()], phase='FINISHED')
        self.assertEqual(api.contest_standings(data, '733439', True), data)
        data = standings([ghost_row()], relativeTimeSeconds=18000)
        self.assertEqual(api.contest_standings(data, '733439', True), data)

    def test_freeze_hides_solutions_at_and_after_boundary(self):
        data = standings([ghost_row()], relativeTimeSeconds=17000, freezeDurationSeconds=10800, frozen=True)
        row = api.contest_standings(data, '733439', True)['result']['rows'][0]
        self.assertEqual((row['points'], row['penalty']), (1, 50))
        data['result']['contest']['phase'] = 'FINISHED'
        self.assertEqual(api.contest_standings(data, '733439', True)['result']['rows'][0]['points'], 1)

    def test_unknown_freeze_boundary_or_clock_never_reveals_final_scores(self):
        for fields in [{'frozen': True}, {'relativeTimeSeconds': None},
                       {'frozen': True, 'freezeDurationSeconds': 19000}, {'phase': 'BEFORE'}]:
            with self.subTest(fields=fields):
                rows = api.contest_standings(standings([ghost_row()], **fields), '733439', True)['result']['rows']
                self.assertEqual((rows[0]['points'], rows[0]['penalty']), (0, 0))

    def test_clock_fallback_uses_contest_start_not_original_party_start(self):
        data = standings([ghost_row()], relativeTimeSeconds=None, startTimeSeconds=10000)
        with patch.object(api.time, 'time', return_value=10600):
            row = api.contest_standings(data, '733439', True)['result']['rows'][0]
        self.assertEqual(row['points'], 1)

    def test_nonstandard_attempt_penalty_and_explicit_problem_penalties(self):
        ghost = ghost_row()
        ghost['penalty'] = 160  # 130 minutes of solve times, three 10-minute penalties.
        self.assertEqual(api.replay_ghost(ghost, 600)['penalty'], 30)
        ghost['problemResults'][0]['penalty'] = 33
        ghost['problemResults'][1]['penalty'] = 141
        ghost['penalty'] = 174
        self.assertEqual(api.replay_ghost(ghost, 600)['penalty'], 33)

    def test_missing_solve_time_is_not_treated_as_an_immediate_solve(self):
        ghost = ghost_row()
        del ghost['problemResults'][0]['bestSubmissionTimeSeconds']
        self.assertEqual(api.replay_ghost(ghost, 600)['points'], 0)

    def test_replay_does_not_expose_final_ioi_ghost_scores_during_contest(self):
        data = standings([ghost_row()])
        self.assertEqual(api.contest_standings(data, '733439', False)['result']['rows'], [])
        data['result']['contest']['type'] = 'IOI'
        self.assertEqual(api.contest_standings(data, '733439', True)['result']['rows'], [])
        data['result']['contest']['phase'] = 'FINISHED'
        self.assertEqual(api.contest_standings(data, '733439', True), data)

    def test_fetch_replays_new_snapshot_after_cache_expires(self):
        api._cache.clear()
        config = {'codeforces_bot_api_key': 'BOT_KEY', 'codeforces_bot_api_secret': 'BOT_SECRET'}
        query = {'contestId': ['733439'], 'groupCode': ['Group42'], 'ghosts': ['true']}
        data = standings([ghost_row()])
        with patch.object(api, 'api_request', return_value=data) as fetch, \
                patch.object(api.time, 'monotonic', return_value=0) as clock:
            status, first = api.fetch_standings(config, query)
            self.assertEqual(status, 200)
            self.assertEqual(first['result']['rows'][0]['points'], 1)
            self.assertEqual(api.fetch_standings(config, query)[1], first)
            self.assertEqual(fetch.call_count, 1)
            data['result']['contest']['relativeTimeSeconds'] = 7200
            clock.return_value = 16
            _, second = api.fetch_standings(config, query)
            self.assertEqual(second['result']['rows'][0]['points'], 2)
            self.assertEqual(first['result']['rows'][0]['points'], 1)
            self.assertEqual(fetch.call_count, 2)
        api._cache.clear()


if __name__ == '__main__':
    unittest.main()
