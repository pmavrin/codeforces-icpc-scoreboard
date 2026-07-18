#!/usr/bin/env python3
"""Serve the scoreboard and proxy signed Codeforces standings requests."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("SCOREBOARD_CONFIG", ROOT / "scoreboard.config.json"))
INDEX_PATH = ROOT / "index.html"
ENV_CONFIG = {
    "api_key": "CODEFORCES_API_KEY",
    "api_secret": "CODEFORCES_API_SECRET",
    "contest_id": "CODEFORCES_CONTEST_ID",
    "group_code": "CODEFORCES_GROUP_CODE",
}


def load_config() -> dict[str, Any]:
    config: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    for key, environment_name in ENV_CONFIG.items():
        value = os.environ.get(environment_name)
        if value:
            config[key] = value

    if os.environ.get("HOST"):
        config["host"] = os.environ["HOST"]
    if os.environ.get("PORT"):
        config["port"] = os.environ["PORT"]

    required = ("api_key", "api_secret", "contest_id", "group_code")
    missing = [key for key in required if not config.get(key)]
    if missing:
        environment_names = ", ".join(ENV_CONFIG[key] for key in missing)
        raise RuntimeError(
            f"Missing config values: {', '.join(missing)}. "
            f"Set {environment_names} or configure {CONFIG_PATH.name}."
        )
    return config


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
            try:
                config = load_config()
            except (RuntimeError, json.JSONDecodeError) as error:
                self.send_json(503, {"status": "FAILED", "comment": str(error)})
                return
            public_config = json.dumps({
                "contestId": config["contest_id"],
                "groupCode": config["group_code"],
                "authRequired": True,
            }, separators=(",", ":")).replace("<", "\\u003c")
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
        try:
            config = load_config()
        except (RuntimeError, json.JSONDecodeError) as error:
            self.send_json(503, {"status": "FAILED", "comment": str(error)})
            return

        contest_id = query.get("contestId", [""])[0]
        group_code = query.get("groupCode", [""])[0]
        if contest_id != str(config["contest_id"]) or group_code != str(config["group_code"]):
            self.send_json(403, {
                "status": "FAILED",
                "comment": "This server is not configured for the requested contest.",
            })
            return

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
                payload = response.read()
                status = response.status
        except urllib.error.HTTPError as error:
            payload = error.read()
            status = error.code
        except (urllib.error.URLError, TimeoutError) as error:
            reason = getattr(error, "reason", str(error))
            self.send_json(502, {"status": "FAILED", "comment": f"Codeforces request failed: {reason}"})
            return
        self.send_bytes(status, "application/json; charset=utf-8", payload, "no-store")


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
