"""Read-only Codeforces standings proxy using a dedicated server-side bot."""

from __future__ import annotations

import hashlib
import http.client
import json
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict


BOT = "pashka-bot"
MAX_BYTES = 16 * 1024 * 1024
_lock = threading.Lock()
_cache = OrderedDict()
_next_call = 0.0


class APIError(Exception):
    def __init__(self, status, message, retry_authenticated=False):
        super().__init__(message)
        self.status = status
        self.retry_authenticated = retry_authenticated


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A signed URL contains credentials; never forward it to another endpoint.
        return None


_opener = urllib.request.build_opener(NoRedirects())


def contest_target(value, group=""):
    value, group = str(value).strip(), str(group or "").strip()
    if group and not re.fullmatch(r"[A-Za-z0-9]{1,64}", group):
        raise ValueError("Enter a valid Codeforces group code.")
    if re.fullmatch(r"[1-9]\d{0,8}", value):
        return value, group
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme not in ("http", "https")
            or parsed.hostname not in ("codeforces.com", "www.codeforces.com")
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 80, 443)):
        raise ValueError("Enter a Codeforces contest ID or contest URL.")
    match = re.fullmatch(r"/(?:group/([A-Za-z0-9]{1,64})/)?(?:contest|gym)/([1-9]\d{0,8})(?:/(?:standings|problems|status))?/?", parsed.path)
    if not match:
        raise ValueError("Enter a contest URL, not a spectator ranklist link.")
    if match[1] and group and match[1] != group:
        raise ValueError("The group code does not match the contest URL.")
    return match[2], match[1] or group


def signed_url(params, key, secret):
    nonce = secrets.token_hex(3)
    ordered = sorted({**params, "apiKey": key, "time": str(int(time.time()))}.items())
    canonical = "&".join(f"{key}={value}" for key, value in ordered)
    signature = hashlib.sha512(f"{nonce}/contest.standings?{canonical}#{secret}".encode()).hexdigest()
    return "https://codeforces.com/api/contest.standings?" + urllib.parse.urlencode(ordered + [("apiSig", nonce + signature)])


def api_request(params, key="", secret=""):
    global _next_call
    # This function is called with _lock held: all viewers share the API quota.
    delay = max(0, _next_call - time.monotonic())
    if delay:
        time.sleep(delay)
    _next_call = time.monotonic() + 2.1
    url = signed_url(params, key, secret) if key else "https://codeforces.com/api/contest.standings?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "ICPC-TV-Scoreboard/1.0"})
    try:
        try:
            response = _opener.open(request, timeout=12)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            status = response.code
            raw = response.read(MAX_BYTES + 1)
    except (OSError, urllib.error.URLError, http.client.HTTPException):
        # Exception strings can contain the signed URL. Never expose them.
        raise APIError(502, "Codeforces API could not be reached. Please retry.") from None
    if len(raw) > MAX_BYTES:
        raise APIError(502, "Codeforces API response is too large.")
    if status == 429:
        raise APIError(429, "Codeforces API rate limit reached. Please retry shortly.")
    if 300 <= status < 400:
        raise APIError(502, "Codeforces API redirected the request; credentials were not forwarded.")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        raise APIError(502, "Codeforces API returned a non-JSON response (possibly Cloudflare). Please retry.") from None
    if not isinstance(data, dict):
        raise APIError(502, "Codeforces API returned an invalid response.")
    if data.get("status") != "OK":
        comment = str(data.get("comment", "")).lower()
        if any(word in comment for word in ("limit exceeded", "too many")):
            raise APIError(429, "Codeforces API rate limit reached. Please retry shortly.")
        if any(word in comment for word in ("apikey", "apisig", "signature", "time:")):
            raise APIError(503, "The server's pashka-bot API credentials need attention. Contact the scoreboard administrator.")
        if any(word in comment for word in ("not found", "access", "denied", "gym", "mashup", "authoriz", "authentic", "permission")):
            raise APIError(403, "pashka-bot cannot view this contest. Check the contest ID and grant pashka-bot access to the group and contest.", retry_authenticated=True)
        raise APIError(502, "Codeforces API rejected the standings request. Check the contest settings and try again.")
    result = data.get("result")
    if (status != 200 or not isinstance(result, dict) or not isinstance(result.get("contest"), dict)
            or not isinstance(result.get("problems"), list) or not isinstance(result.get("rows"), list)):
        raise APIError(502, "Codeforces API returned invalid standings.")
    # Only the standings result is public, never upstream diagnostic fields.
    return {"status": "OK", "result": {name: result[name] for name in ("contest", "problems", "rows")}}


def fetch_standings(config, query):
    def failure(status, message):
        return status, {"status": "FAILED", "comment": message}

    value = query.get("contestId", query.get("contest", query.get("url", [config.get("codeforces_url") or config.get("contest_id", "")])))[0]
    default_group = "" if any(name in query for name in ("contestId", "contest", "url")) else config.get("group_code", "")
    group = query.get("groupCode", query.get("group", [default_group]))[0]
    try:
        contest_id, group = contest_target(value, group)
    except ValueError as error:
        return failure(400, str(error))
    # Deliberately ignore legacy personal keys in old JSON files and all query credentials.
    key, secret = str(config.get("codeforces_bot_api_key") or ""), str(config.get("codeforces_bot_api_secret") or "")
    if group and not (key and secret):
        return failure(503, "The server is not configured for pashka-bot. Set CODEFORCES_API_KEY and CODEFORCES_API_SECRET on Render.")
    fingerprint = hashlib.sha256(json.dumps([key, secret]).encode()).hexdigest()
    cache_key = (contest_id, group, fingerprint)
    if not _lock.acquire(blocking=False):
        return failure(429, "Codeforces API is busy. Please retry shortly.")
    try:
        cached = _cache.get(cache_key)
        if cached and cached[0] > time.monotonic():
            return cached[1], cached[2]
        try:
            data = None
            if not group:
                try:
                    # Regular public contests accept exactly this one anonymous parameter.
                    data = api_request({"contestId": contest_id})
                except APIError as error:
                    if not error.retry_authenticated:
                        raise
            if data is None:
                if not (key and secret):
                    raise APIError(503, "This contest requires the server's pashka-bot credentials. Set CODEFORCES_API_KEY and CODEFORCES_API_SECRET on Render.")
                params = {"contestId": contest_id, "showUnofficial": "true"}
                if group:
                    params["groupCode"] = group
                # Never enable asManager: respect the participant-visible scoreboard and freeze.
                data = api_request(params, key, secret)
            status = 200
        except APIError as error:
            status, data = failure(error.status, str(error))
        _cache[cache_key] = (time.monotonic() + (15 if status == 200 else 2), status, data)
        _cache.move_to_end(cache_key)
        while len(_cache) > 32:
            _cache.popitem(last=False)
        return status, data
    finally:
        _lock.release()
