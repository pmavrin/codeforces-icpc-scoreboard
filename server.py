#!/usr/bin/env python3
"""Serve the scoreboard and proxy standings requests."""

from __future__ import annotations

import hashlib
import html
import re
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("SCOREBOARD_CONFIG", ROOT / "scoreboard.config.json"))
INDEX_PATH = ROOT / "index.html"
ENV_CONFIG = {
    "api_key": "CODEFORCES_API_KEY",
    "api_secret": "CODEFORCES_API_SECRET",
    "contest_id": "CODEFORCES_CONTEST_ID",
    "group_code": "CODEFORCES_GROUP_CODE",
    "source": "SCOREBOARD_SOURCE",
    "opencup_url": "OPENCUP_STANDINGS_URL",
    "university_aliases": "UNIVERSITY_ALIASES",
}


@dataclass(frozen=True)
class StandingsSource:
    label: str
    required_config: tuple[str, ...]
    public_config: Callable[[dict[str, Any]], dict[str, Any]]
    fetch: Callable[[dict[str, Any], dict[str, list[str]]], tuple[int, str, bytes]]
    query_config: Callable[[dict[str, list[str]]], dict[str, Any]]


def load_config() -> dict[str, Any]:
    config: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    for key, environment_name in ENV_CONFIG.items():
        value = os.environ.get(environment_name)
        if value:
            if key == "university_aliases":
                config[key] = json.loads(value)
            else:
                config[key] = value

    if os.environ.get("HOST"):
        config["host"] = os.environ["HOST"]
    if os.environ.get("PORT"):
        config["port"] = os.environ["PORT"]

    source = normalize_source(config.get("source", "codeforces"))
    config["source"] = source
    adapter = STANDINGS_SOURCES[source]
    required = adapter.required_config
    missing = [key for key in required if not config.get(key)]
    if missing:
        environment_names = ", ".join(ENV_CONFIG.get(key, key) for key in missing)
        raise RuntimeError(
            f"Missing config values: {', '.join(missing)}. "
            f"Set {environment_names} or configure {CONFIG_PATH.name}."
        )
    return config


def normalize_source(value: Any) -> str:
    source = str(value or "codeforces").lower()
    if source not in STANDINGS_SOURCES:
        supported = ", ".join(sorted(STANDINGS_SOURCES))
        raise RuntimeError(f"Unsupported standings source: {source}. Supported sources: {supported}.")
    return source


def json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def failed_json(status: int, comment: str) -> tuple[int, str, bytes]:
    return status, "application/json; charset=utf-8", json_bytes({"status": "FAILED", "comment": comment})


def request_source(query: dict[str, list[str]]) -> str | None:
    requested = query.get("source", [""])[0]
    if not requested:
        return None
    source = str(requested).lower()
    return source if source in STANDINGS_SOURCES else None


def load_request_config(query: dict[str, list[str]]) -> dict[str, Any]:
    source = request_source(query)
    if source:
        config = STANDINGS_SOURCES[source].query_config(query)
        config["source"] = source
        return config
    return load_config()


def parse_duration_to_seconds(value: str) -> int:
    parts = [int(part) for part in value.strip().split(":") if part.isdigit()]
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours, minutes = parts
        seconds = 0
    elif len(parts) == 1:
        hours, minutes, seconds = 0, parts[0], 0
    else:
        return 0
    return hours * 3600 + minutes * 60 + seconds


class StandingsTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.table_depth = 0
        self.in_standings = False
        self.in_head = False
        self.in_body = False
        self.in_row = False
        self.current_cells: list[dict[str, Any]] = []
        self.current_cell: dict[str, Any] | None = None
        self.found_standings = False
        self.problems: list[dict[str, Any]] = []
        self.rows: list[list[dict[str, Any]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name: value or "" for name, value in attrs}
        class_names = set(attrs_dict.get("class", "").split())
        if tag == "table" and "standings" in class_names:
            self.in_standings = True
            self.found_standings = True
            self.table_depth = 1
            return
        if not self.in_standings:
            return
        if tag == "table":
            self.table_depth += 1
        elif tag == "thead":
            self.in_head = True
        elif tag == "tbody":
            self.in_body = True
        elif tag == "tr" and (self.in_head or self.in_body):
            self.in_row = True
            self.current_cells = []
        elif tag in ("th", "td") and self.in_row:
            self.current_cell = {
                "tag": tag,
                "classes": class_names,
                "title": attrs_dict.get("title", ""),
                "first_to_solve": "first-to-solve" in class_names,
                "text": [],
            }
        elif self.current_cell is not None and "first-to-solve" in class_names:
            self.current_cell["first_to_solve"] = True
        elif tag == "br" and self.current_cell is not None:
            self.current_cell["text"].append("\n")

    def handle_endtag(self, tag: str) -> None:
        if not self.in_standings:
            return
        if tag in ("th", "td") and self.current_cell is not None:
            self.current_cells.append(self.current_cell)
            self.current_cell = None
        elif tag == "tr" and self.in_row:
            if self.in_head:
                self._parse_header(self.current_cells)
            elif self.in_body and self.current_cells:
                self.rows.append(self.current_cells)
            self.in_row = False
            self.current_cells = []
        elif tag == "thead":
            self.in_head = False
        elif tag == "tbody":
            self.in_body = False
        elif tag == "table":
            self.table_depth -= 1
            if self.table_depth <= 0:
                self.in_standings = False

    def handle_data(self, data: str) -> None:
        if self.current_cell is not None:
            self.current_cell["text"].append(data)

    def _parse_header(self, cells: list[dict[str, Any]]) -> None:
        for cell in cells:
            if "problem" not in cell["classes"]:
                continue
            label = normalize_spaces("".join(cell["text"]))
            self.problems.append({
                "index": label,
                "name": cell["title"] or f"Problem {label}",
                "points": 1,
            })


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def parse_opencup_cell(cell: dict[str, Any]) -> dict[str, Any]:
    text = normalize_spaces("".join(cell["text"]))
    if not text or text == ".":
        return {"points": 0, "rejectedAttemptCount": 0}
    accepted = text.startswith("+")
    rejected_match = re.match(r"^[+\-−](\d+)?", text)
    rejected = int(rejected_match.group(1) or 0) if rejected_match else 0
    result: dict[str, Any] = {
        "points": 1 if accepted else 0,
        "rejectedAttemptCount": rejected,
    }
    if accepted and cell.get("first_to_solve"):
        result["firstToSolve"] = True
    time_match = re.search(r"(\d{1,2}:\d{2}(?::\d{2})?)", text)
    if accepted and time_match:
        result["bestSubmissionTimeSeconds"] = parse_duration_to_seconds(time_match.group(1))
    return result


def parse_opencup_standings(page: str, source_url: str) -> dict[str, Any]:
    parser = StandingsTableParser()
    parser.feed(page)
    if not parser.found_standings or not parser.problems:
        raise ValueError("OpenCup standings table was not found in the HTML page.")

    title_match = re.search(r"<h2[^>]*>(.*?)</h2>", page, re.IGNORECASE | re.DOTALL)
    contest_name = normalize_spaces(title_match.group(1)) if title_match else "OpenCup Standings"
    progress_match = re.search(r"(\d+:\d{2}:\d{2})\s+of\s+(\d+:\d{2}:\d{2})", page)
    elapsed_seconds = parse_duration_to_seconds(progress_match.group(1)) if progress_match else 0
    duration_seconds = parse_duration_to_seconds(progress_match.group(2)) if progress_match else 0
    over = bool(re.search(r"status:\s*over", page, re.IGNORECASE))
    now = int(time.time())
    start_time = now - elapsed_seconds if elapsed_seconds else now - duration_seconds
    rows = []

    for row_index, cells in enumerate(parser.rows):
        if len(cells) < len(parser.problems) + 4:
            continue
        rank_text = normalize_spaces("".join(cells[0]["text"]))
        team_name = normalize_spaces("".join(cells[1]["text"]))
        problem_cells = cells[2:2 + len(parser.problems)]
        solved_cell = cells[2 + len(parser.problems)]
        penalty_cell = cells[3 + len(parser.problems)]
        problem_results = [parse_opencup_cell(cell) for cell in problem_cells]
        try:
            rank: int | str = int(rank_text)
        except ValueError:
            rank = rank_text or row_index + 1
        rows.append({
            "rank": rank,
            "points": int(normalize_spaces("".join(solved_cell["text"])) or 0),
            "penalty": int(normalize_spaces("".join(penalty_cell["text"])) or 0),
            "party": {
                "participantType": "CONTESTANT",
                "teamId": row_index + 1,
                "teamName": team_name,
                "members": [],
            },
            "problemResults": problem_results,
        })

    return {
        "status": "OK",
        "result": {
            "contest": {
                "id": "opencup",
                "name": contest_name,
                "phase": "FINISHED" if over else "CODING",
                "durationSeconds": duration_seconds,
                "startTimeSeconds": start_time,
                "sourceUrl": source_url,
            },
            "problems": parser.problems,
            "rows": rows,
        },
    }


def signed_codeforces_url(config: dict[str, Any], params: dict[str, str]) -> str:
    method_name = "contest.standings"
    rand = secrets.token_hex(3)
    signed_params = {
        **params,
        "apiKey": str(config["api_key"]),
        "time": str(int(time.time())),
    }
    ordered = sorted(signed_params.items(), key=lambda item: (item[0], item[1]))
    canonical_query = "&".join(f"{key}={value}" for key, value in ordered)
    signature_source = f"{rand}/{method_name}?{canonical_query}#{config['api_secret']}"
    signature = hashlib.sha512(signature_source.encode("utf-8")).hexdigest()
    query = urllib.parse.urlencode([*ordered, ("apiSig", rand + signature)])
    return f"https://codeforces.com/api/{method_name}?{query}"


def codeforces_public_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "codeforces",
        "sourceLabel": "Codeforces",
        "universityAliases": config.get("university_aliases", {}),
        "contestId": config.get("contest_id"),
        "groupCode": config.get("group_code", ""),
        "opencupUrl": "",
        "authRequired": True,
    }


def codeforces_query_config(query: dict[str, list[str]]) -> dict[str, Any]:
    return {}


def fetch_codeforces_standings(
    config: dict[str, Any],
    query: dict[str, list[str]],
) -> tuple[int, str, bytes]:
    contest_id = query.get("contestId", [""])[0]
    group_code = query.get("groupCode", [""])[0]
    if contest_id != str(config["contest_id"]) or group_code != str(config["group_code"]):
        return failed_json(403, "This server is not configured for the requested contest.")

    try:
        count = max(1, min(500, int(query.get("count", ["200"])[0])))
    except ValueError:
        count = 200
    show_unofficial = query.get("showUnofficial", ["true"])[0].lower() == "true"
    participant_types = "CONTESTANT,OUT_OF_COMPETITION" if show_unofficial else "CONTESTANT"
    params = {
        "asManager": "true",
        "contestId": contest_id,
        "count": str(count),
        "from": "1",
        "groupCode": group_code,
        "participantTypes": participant_types,
    }
    codeforces_url = signed_codeforces_url(config, params)
    request = urllib.request.Request(
        codeforces_url,
        headers={"Accept": "application/json", "User-Agent": "ICPC-TV-Scoreboard/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return response.status, "application/json; charset=utf-8", response.read()
    except urllib.error.HTTPError as error:
        return error.code, "application/json; charset=utf-8", error.read()
    except (urllib.error.URLError, TimeoutError) as error:
        reason = getattr(error, "reason", str(error))
        return failed_json(502, f"Codeforces request failed: {reason}")


def opencup_public_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "opencup",
        "sourceLabel": "OpenCup",
        "universityAliases": config.get("university_aliases", {}),
        "contestId": None,
        "groupCode": "",
        "opencupUrl": config.get("opencup_url", ""),
        "authRequired": False,
    }


def opencup_query_config(query: dict[str, list[str]]) -> dict[str, Any]:
    return {
        "source": "opencup",
        "opencup_url": query.get("url", [""])[0],
    }


def fetch_opencup_standings(
    config: dict[str, Any],
    query: dict[str, list[str]],
) -> tuple[int, str, bytes]:
    source_url = str(config.get("opencup_url") or query.get("url", [""])[0])
    parsed_url = urllib.parse.urlparse(source_url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        return failed_json(400, "A valid OpenCup standings URL is required.")
    request = urllib.request.Request(
        source_url,
        headers={"Accept": "text/html,*/*;q=0.8", "User-Agent": "ICPC-TV-Scoreboard/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
        page = raw.decode(charset, errors="replace")
        payload = parse_opencup_standings(page, source_url)
        return 200, "application/json; charset=utf-8", json_bytes(payload)
    except urllib.error.HTTPError as error:
        return failed_json(error.code, f"OpenCup returned HTTP {error.code}")
    except (urllib.error.URLError, TimeoutError) as error:
        reason = getattr(error, "reason", str(error))
        return failed_json(502, f"OpenCup request failed: {reason}")
    except (UnicodeError, ValueError) as error:
        return failed_json(502, f"OpenCup parse failed: {error}")


STANDINGS_SOURCES: dict[str, StandingsSource] = {
    "codeforces": StandingsSource(
        label="Codeforces",
        required_config=("api_key", "api_secret", "contest_id", "group_code"),
        public_config=codeforces_public_config,
        fetch=fetch_codeforces_standings,
        query_config=codeforces_query_config,
    ),
    "opencup": StandingsSource(
        label="OpenCup",
        required_config=("opencup_url",),
        public_config=opencup_public_config,
        fetch=fetch_opencup_standings,
        query_config=opencup_query_config,
    ),
}


class ScoreboardHandler(BaseHTTPRequestHandler):
    server_version = "ICPCScoreboard/1.0"

    def send_bytes(self, status: int, content_type: str, payload: bytes, cache_control: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_bytes(status, "application/json; charset=utf-8", body, "no-store")

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        request = urllib.parse.urlparse(self.path)
        if request.path == "/health":
            try:
                load_config()
            except (RuntimeError, json.JSONDecodeError) as error:
                self.send_json(503, {"status": "FAILED", "comment": str(error)})
                return
            self.send_json(200, {"status": "OK"})
            return
        if request.path in ("/", "/index.html"):
            page_query = urllib.parse.parse_qs(request.query)
            if page_query.get("source", [""])[0] and request_source(page_query) is None:
                self.send_json(400, {"status": "FAILED", "comment": "Unsupported standings source."})
                return
            try:
                config = load_request_config(page_query)
            except (RuntimeError, json.JSONDecodeError) as error:
                self.send_json(503, {"status": "FAILED", "comment": str(error)})
                return
            adapter = STANDINGS_SOURCES[normalize_source(config.get("source"))]
            public_config = json.dumps(adapter.public_config(config), separators=(",", ":")).replace("<", "\\u003c")
            page = INDEX_PATH.read_text(encoding="utf-8").replace(
                '<script id="serverConfig" type="application/json">null</script>',
                f'<script id="serverConfig" type="application/json">{public_config}</script>',
                1,
            ).encode("utf-8")
            self.send_bytes(
                200,
                "text/html; charset=utf-8",
                page,
                "no-cache",
            )
            return
        if request.path == "/api/standings":
            self.serve_standings(urllib.parse.parse_qs(request.query))
            return
        self.send_json(404, {"status": "FAILED", "comment": "Not found"})

    def serve_standings(self, query: dict[str, list[str]]) -> None:
        if query.get("source", [""])[0] and request_source(query) is None:
            self.send_json(400, {"status": "FAILED", "comment": "Unsupported standings source."})
            return

        try:
            config = load_request_config(query)
        except (RuntimeError, json.JSONDecodeError) as error:
            self.send_json(503, {"status": "FAILED", "comment": str(error)})
            return

        adapter = STANDINGS_SOURCES[normalize_source(config.get("source"))]
        status, content_type, payload = adapter.fetch(config, query)
        self.send_bytes(status, content_type, payload, "no-store")


def main() -> None:
    config = load_config()
    host = str(config.get("host", "0.0.0.0"))
    port = int(config.get("port", 8080))
    server = ThreadingHTTPServer((host, port), ScoreboardHandler)
    print(f"Scoreboard available at http://{host}:{port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
