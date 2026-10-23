import json
import re
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import server
from domjudge import parse_domjudge_standings


FIXTURES = Path(__file__).parent / "fixtures"
URL = "https://judge.example/public?contest=42"


class DOMjudgeTests(unittest.TestCase):
    def setUp(self):
        self.page = (FIXTURES / "domjudge-modern.html").read_text()

    def parse(self, page=None, url=URL):
        return parse_domjudge_standings(self.page if page is None else page, url)["result"]

    def test_modern_scoreboard(self):
        result = self.parse()
        self.assertEqual(result["contest"]["name"], "Example & Contest")
        self.assertEqual(result["contest"]["durationSeconds"], 18000)
        self.assertEqual(result["contest"]["phase"], "CODING")
        self.assertEqual([p["index"] for p in result["problems"]], list("ABCD"))
        self.assertEqual(len(result["rows"]), 2)
        first, second = result["rows"]
        self.assertEqual(first["party"]["teamName"], "Seems to be O(k!)")
        self.assertEqual(first["party"]["university"], "University & Institute")
        self.assertEqual(second["party"]["teamName"], "<Dom>ination")
        self.assertEqual(second["rank"], 1)
        self.assertEqual((first["points"], first["penalty"]), (1, 40))
        self.assertEqual(first["problemResults"], [
            {"points": 1, "rejectedAttemptCount": 2, "bestSubmissionTimeSeconds": 0, "firstToSolve": True},
            {"points": 0, "rejectedAttemptCount": 4},
            {"points": 0, "rejectedAttemptCount": 1, "frozen": True, "pendingAttemptCount": 2},
            {"points": 0, "rejectedAttemptCount": 0},
        ])

    def test_legacy_static_scoreboard(self):
        result = self.parse((FIXTURES / "domjudge-legacy.html").read_text())
        self.assertEqual([p["index"] for p in result["problems"]], ["boolfind", "fltcmp", "hello"])
        self.assertEqual(result["contest"]["phase"], "FINISHED")
        self.assertFalse(result["contest"]["timingAvailable"])
        self.assertIsNone(result["contest"]["startTimeSeconds"])
        self.assertEqual(len(result["rows"]), 1)
        row = result["rows"][0]
        self.assertTrue(row["party"]["teamId"].endswith(":2"))
        self.assertEqual(row["party"]["university"], "Utrecht University")
        self.assertEqual(row["problemResults"][0]["bestSubmissionTimeSeconds"], 5400)
        self.assertEqual(row["problemResults"][0]["rejectedAttemptCount"], 1)
        self.assertEqual(row["problemResults"][1]["pendingAttemptCount"], 3)
        self.assertEqual(row["problemResults"][1]["rejectedAttemptCount"], 0)

    def test_team_identity_survives_reordering_and_rename(self):
        rows = re.findall(r'<tr data-team-id=.*?</tr>', self.page, re.S)
        reordered = self.page.replace(rows[0], "ROW_PLACEHOLDER").replace(rows[1], rows[0]).replace("ROW_PLACEHOLDER", rows[1])
        before = {r["party"]["teamName"]: r["party"]["teamId"] for r in self.parse()["rows"]}
        after = {r["party"]["teamName"]: r["party"]["teamId"] for r in self.parse(reordered)["rows"]}
        self.assertEqual(before, after)
        renamed = self.parse(self.page.replace("Seems to be O(k!)", "Renamed team"))
        self.assertEqual(renamed["rows"][0]["party"]["teamId"], before["Seems to be O(k!)"])
        other_contest = self.parse(url="https://judge.example/public?contest=43")
        self.assertNotEqual(other_contest["rows"][0]["party"]["teamId"], before["Seems to be O(k!)"])

    def test_empty_scoreboard_and_invalid_page(self):
        empty = re.sub(r'<tr data-team-id=.*?</tr>', '', self.page, flags=re.S)
        self.assertEqual(self.parse(empty)["rows"], [])
        with self.assertRaisesRegex(ValueError, "table was not found"):
            self.parse('<html><h1>Login</h1></html>')
        with self.assertRaisesRegex(ValueError, "problem columns"):
            self.parse('<table class="scoreboard"></table>')
        with self.assertRaisesRegex(ValueError, "count does not match"):
            self.parse(self.page.replace('<td class="score_cell" data-problem="D"></td>', '', 1))

    def test_clock_phases_and_fractional_timestamps(self):
        before = self.page.replace('var initial = 1764496800;', 'var initial = 1764490000;')
        self.assertEqual(self.parse(before)["contest"]["phase"], "BEFORE")
        after = self.page.replace('var initial = 1764496800;', 'var initial = 1764511200;')
        self.assertEqual(self.parse(after)["contest"]["phase"], "FINISHED")
        fractional = self.page.replace('var starttime = 1764493200;', 'var starttime = 1764493200.000000000;')
        self.assertEqual(self.parse(fractional)["contest"]["durationSeconds"], 18000)

    def test_query_configuration_keeps_aliases_and_default_url(self):
        config = {"source": "opencup", "domjudge_url": URL, "university_aliases": {"University & Institute": "UI"}}
        with patch.object(server, "load_raw_config", return_value=config):
            result = server.load_request_config({"source": ["domjudge"]})
            self.assertEqual(result["domjudge_url"], URL)
            public = server.domjudge_public_config(result)
            self.assertEqual(public["universityAliases"], config["university_aliases"])
            self.assertEqual(public["standingsUrl"], URL)
            self.assertFalse(public["authRequired"])
            override = server.load_request_config({"source": ["domjudge"], "url": ["https://other.example/public"]})
            self.assertEqual(override["domjudge_url"], "https://other.example/public")

    def test_fetch_adapter_and_failures(self):
        with patch.object(server, "read_public_html", return_value=self.page):
            status, content_type, body = server.fetch_domjudge_standings({"domjudge_url": URL}, {})
        self.assertEqual(status, 200)
        self.assertIn("application/json", content_type)
        self.assertEqual(json.loads(body)["status"], "OK")
        self.assertEqual(server.fetch_domjudge_standings({"domjudge_url": "file:///etc/passwd"}, {})[0], 400)
        with patch.object(server, "read_public_html", side_effect=urllib.error.URLError("offline")):
            self.assertEqual(server.fetch_domjudge_standings({"domjudge_url": URL}, {})[0], 502)
        with patch.object(server, "read_public_html", return_value='<html>Login</html>'):
            status, _, body = server.fetch_domjudge_standings({"domjudge_url": URL}, {})
        self.assertEqual(status, 502)
        self.assertEqual(json.loads(body)["status"], "FAILED")


if __name__ == "__main__":
    unittest.main()
