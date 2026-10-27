"""Read Codeforces spectator ranklists without the authenticated API."""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

from domjudge import DOMjudgeHTMLParser, Element


def spectator_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (parsed.scheme not in ("http", "https")
            or parsed.hostname not in ("codeforces.com", "www.codeforces.com", "mirror.codeforces.com")
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 80, 443)
            or not re.fullmatch(r"/spectator/ranklist/[A-Za-z0-9_-]+/?", parsed.path)):
        raise ValueError("Enter a Codeforces spectator ranklist URL: https://codeforces.com/spectator/ranklist/...")
    # The link token identifies the ranklist. Discard browser filters and fragments.
    return urlunsplit(("https", parsed.hostname, parsed.path.rstrip("/"), "", ""))


def inline_text(node: Element) -> str:
    # Codeforces wraps the first letter of legendary handles in its own span.
    return "".join(inline_text(child) if isinstance(child, Element) else child for child in node.children)


def clock_seconds(value: str) -> int:
    if not re.fullmatch(r"\d+:[0-5]\d(?::[0-5]\d)?", value):
        raise ValueError(f"Cannot read Codeforces time: {value!r}")
    parts = [int(part) for part in value.split(":")]
    return parts[0] * 3600 + parts[1] * 60 + (parts[2] if len(parts) == 3 else 0)


def parse_cell(cell: Element) -> dict[str, Any]:
    accepted = cell.by_class("cell-accepted")
    rejected = cell.by_class("cell-rejected")
    time_node = cell.by_class("cell-time")
    value = (accepted or rejected or cell).text().strip().replace("\u2212", "-")
    result: dict[str, Any] = {"points": 0, "rejectedAttemptCount": 0}
    if not value:
        return result
    if re.fullmatch(r"\+\d*", value):
        if time_node is None:
            raise ValueError("Codeforces accepted submission has no solve time.")
        result.update(points=1, rejectedAttemptCount=int(value[1:] or 0),
                      bestSubmissionTimeSeconds=clock_seconds(time_node.text()))
    elif re.fullmatch(r"-\d+", value):
        result["rejectedAttemptCount"] = int(value[1:])
    elif re.fullmatch(r"\?\d*", value):
        result.update(frozen=True, pendingAttemptCount=int(value[1:] or 0))
    else:
        raise ValueError(f"Unsupported Codeforces ICPC cell: {value!r}")
    return result


def parse_codeforces_standings(page: str, source_url: str) -> dict[str, Any]:
    source_url = spectator_url(source_url)
    parser = DOMjudgeHTMLParser()
    parser.feed(page)
    root = parser.root
    table = next((node for node in root.elements("table") if node.has_class("standings")), None)
    if table is None:
        raise ValueError("Codeforces spectator table was not found. The link may be invalid or blocked by Cloudflare.")
    header = next(table.elements("tr"), None)
    headings = list(header.elements("th")) if header else []
    if (len(headings) < 5 or headings[2].text() != "="
            or headings[3].text().lower() not in ("penalty", "\u0448\u0442\u0440\u0430\u0444")):
        raise ValueError("Only Codeforces ICPC spectator ranklists with solved and penalty columns are supported.")
    labels = [heading.text() for heading in headings[4:]]
    if len(set(labels)) != len(labels) or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", label) for label in labels):
        raise ValueError("Cannot read Codeforces problem columns.")
    problems = [{"index": label, "name": f"Problem {label}", "points": 1} for label in labels]
    name_node, status_node = root.by_class("contest-name"), root.by_class("contest-status")
    name = name_node.text() if name_node else "Codeforces spectator ranklist"
    status = status_node.text().lower() if status_node else ""
    phase = ("FINISHED" if any(word in status for word in ("finished", "over", "ended", "\u0437\u0430\u043a\u043e\u043d\u0447", "\u0437\u0430\u0432\u0435\u0440\u0448"))
             else "BEFORE" if any(word in status for word in ("not started", "before", "\u043d\u0435 \u043d\u0430\u0447")) else "CODING")
    # No start time or duration is exposed here. Preserve the displayed countdown instead.
    identity = hashlib.sha256(urlsplit(source_url).path.encode()).hexdigest()[:16]
    contest: dict[str, Any] = {
        "id": f"codeforces:{identity}", "name": name, "phase": phase,
        "timingAvailable": False, "startTimeSeconds": None, "durationSeconds": 0,
        "sourceUrl": source_url,
    }
    countdown = root.by_class("countdown")
    if countdown and phase != "FINISHED":
        contest.update(remainingTimeSeconds=clock_seconds(countdown.text()), observedAtSeconds=time.time())

    rows = []
    problem_ids = None
    for row in table.elements("tr"):
        participant_id = row.attrs.get("participantid")
        if not participant_id:
            continue
        cells = [child for child in row.children if isinstance(child, Element) and child.tag == "td"]
        who = row.by_class("contestant-cell")
        if who is None or len(cells) != len(problems) + 4:
            raise ValueError("Codeforces participant row does not match the problem columns.")
        ids = [(cell.attrs.get("contestid"), cell.attrs.get("problemid")) for cell in cells[4:]]
        if any(not contest_id or not problem_id for contest_id, problem_id in ids):
            raise ValueError("Codeforces problem identities are missing.")
        if problem_ids is not None and ids != problem_ids:
            raise ValueError("Codeforces problem order is inconsistent.")
        problem_ids = ids
        team = None
        members = []
        for link in who.elements("a"):
            path = urlsplit(link.attrs.get("href", "")).path
            if re.fullmatch(r"/team/\d+", path):
                team = " ".join(inline_text(link).split())
            elif path.startswith("/profile/"):
                members.append({"handle": unquote(path[len("/profile/"):])})
        if not team and not members:
            raise ValueError("Codeforces participant name was not found.")
        rank = cells[0].text()
        unofficial = not rank.isdigit()
        rows.append({
            "rank": int(rank) if rank.isdigit() else rank,
            "points": int(cells[2].text()), "penalty": int(cells[3].text()),
            "party": {
                "participantType": "OUT_OF_COMPETITION" if unofficial else "CONTESTANT",
                "teamId": f"{contest['id']}:{participant_id}",
                "teamName": team or "", "members": members,
            },
            "problemResults": [parse_cell(cell) for cell in cells[4:]],
        })
    return {"status": "OK", "result": {"contest": contest, "problems": problems, "rows": rows}}
