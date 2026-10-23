"""Read public DOMjudge ICPC scoreboards, including static HTML exports."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Iterator


@dataclass
class Element:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[Any] = field(default_factory=list)

    def has_class(self, name: str) -> bool:
        return name in self.attrs.get("class", "").split()

    def elements(self, tag: str | None = None) -> Iterator[Element]:
        for child in self.children:
            if isinstance(child, Element):
                if tag is None or child.tag == tag:
                    yield child
                yield from child.elements(tag)

    def text(self) -> str:
        return " ".join(" ".join(
            child.text() if isinstance(child, Element) else child
            for child in self.children
        ).split())

    def by_class(self, name: str) -> Element | None:
        return next((node for node in self.elements() if node.has_class(name)), None)


class DOMjudgeHTMLParser(HTMLParser):
    VOID_TAGS = frozenset("area base br col embed hr img input link meta param source track wbr".split())

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("document")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Element(tag, {key: value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag == "br":
            self.stack[-1].children.append(" ")
        if tag not in self.VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def parse_domjudge_cell(cell: Element) -> dict[str, Any]:
    classes = set(cell.attrs.get("class", "").split())
    for node in cell.elements():
        classes.update(node.attrs.get("class", "").split())
    text = cell.text()
    attempts = re.search(r"(\d+)(?:\s*\+\s*(\d+))?\s+tr(?:y|ies)\b", text)
    judged = int(attempts.group(1)) if attempts else 0
    pending = int(attempts.group(2) or 0) if attempts else 0
    accepted = "score_correct" in classes
    result: dict[str, Any] = {
        "points": 1 if accepted else 0,
        "rejectedAttemptCount": max(0, judged - 1) if accepted else judged,
    }
    if accepted:
        if not attempts:
            raise ValueError(f"Cannot read DOMjudge submission count: {text!r}")
        # DOMjudge displays minutes before the submission-count span.
        minutes = re.fullmatch(r"\s*(\d+)\s*", text[:attempts.start()])
        if not minutes:
            raise ValueError(f"Cannot read DOMjudge solve time: {text!r}")
        result["bestSubmissionTimeSeconds"] = int(minutes.group(1)) * 60
        if "score_first" in classes:
            result["firstToSolve"] = True
    elif "score_pending" in classes:
        # Older versions may show only the total pending count, without '+'.
        if attempts and attempts.group(2) is None:
            pending, result["rejectedAttemptCount"] = judged, 0
        result.update(frozen=True, pendingAttemptCount=pending)
    elif "score_incorrect" in classes and not attempts:
        raise ValueError(f"Cannot read DOMjudge submission count: {text!r}")
    return result


def domjudge_contest(root: Element, source_url: str) -> dict[str, Any]:
    header = root.by_class("card-header")
    name_node = next(header.elements("span"), None) if header else None
    if name_node is None:
        name_node = next(root.elements("h1"), None) or next(root.elements("title"), None)
    name = name_node.text() if name_node else "DOMjudge Standings"
    scripts = "\n".join(node.text() for node in root.elements("script"))

    def timestamp(variable: str) -> float | None:
        match = re.search(r"\b(?:var|let|const)\s+" + variable + r"\s*=\s*(\d+(?:\.\d+)?)\s*;", scripts)
        return float(match.group(1)) if match else None

    start, end = timestamp("starttime"), timestamp("endtime")
    now = timestamp("initial")
    if now is None:
        now = time.time()
    timing_available = start is not None and end is not None and end >= start
    timer = next((node for node in root.elements() if node.attrs.get("id") == "contesttimer"), None)
    status = (timer.text() if timer else header.text() if header else "").lower()
    if timing_available:
        phase = "BEFORE" if now < start else "FINISHED" if now >= end else "CODING"
    else:
        phase = "FINISHED" if "contest over" in status or "final standings" in status else "CODING"
    identity = hashlib.sha1(f"{source_url}\n{name}".encode("utf-8")).hexdigest()[:12]
    return {
        "id": f"domjudge:{identity}",
        "name": name,
        "phase": phase,
        "durationSeconds": int(end - start) if timing_available else 0,
        "startTimeSeconds": start if timing_available else None,
        "timingAvailable": timing_available,
        "sourceUrl": source_url,
    }


def parse_domjudge_standings(page: str, source_url: str) -> dict[str, Any]:
    parser = DOMjudgeHTMLParser()
    parser.feed(page)
    root = parser.root
    # The legend and team-detail dialogs also contain tables. Only read the main scoreboard.
    table = next((node for node in root.elements("table")
                  if node.has_class("scoreboard") and not node.has_class("scorelegend")
                  and node.attrs.get("id") != "cell_legend"), None)
    if table is None:
        raise ValueError("DOMjudge scoreboard table was not found. Use a public scoreboard URL or static export.")
    problems = []
    for heading in table.elements("th"):
        attrs = heading.attrs
        if "data-problem-id" not in attrs and not attrs.get("title", "").lower().startswith("problem "):
            continue
        badge = heading.by_class("problem-badge")
        label = badge.text() if badge else heading.text()
        problems.append({
            "index": label,
            "name": attrs.get("data-problem-name") or attrs.get("title", "")[8:] or f"Problem {label}",
            "points": 1,
        })
    if not problems:
        raise ValueError("DOMjudge problem columns were not found in the scoreboard.")

    contest = domjudge_contest(root, source_url)
    rows = []
    for row in table.elements("tr"):
        team = row.by_class("scoretn")
        if team is None:
            continue
        name = row.attrs.get("data-team-name") or team.attrs.get("title")
        university = team.by_class("univ")
        if not name:
            name_span = team.by_class("forceWidth")
            name = name_span.text() if name_span else team.text()
        name = " ".join(name.split())
        team_id = row.attrs.get("data-team-id") or row.attrs.get("id", "").removeprefix("team:")
        if not team_id:
            identity = f"{name}\n{university.text() if university else ''}"
            team_id = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
        solved, penalty = row.by_class("scorenc"), row.by_class("scorett")
        if solved is None or penalty is None:
            raise ValueError("DOMjudge ICPC solved/penalty columns were not found.")
        problem_cells = [node for node in row.elements("td") if node.has_class("score_cell")]
        if len(problem_cells) != len(problems):
            raise ValueError(f"DOMjudge problem count does not match for team {name!r}.")
        # New versions label cells; older versions use the header order.
        if all(cell.attrs.get("data-problem") for cell in problem_cells):
            by_label = {cell.attrs["data-problem"]: cell for cell in problem_cells}
            if set(by_label) != {problem["index"] for problem in problems}:
                raise ValueError(f"DOMjudge problem labels do not match for team {name!r}.")
            problem_cells = [by_label[problem["index"]] for problem in problems]
        points, penalty_minutes = int(solved.text()), int(penalty.text())
        rank_cell = row.by_class("scorepl")
        rank_text = rank_cell.text() if rank_cell else ""
        if rank_text:
            rank = int(rank_text) if rank_text.isdigit() else rank_text
        elif rows and (rows[-1]["points"], rows[-1]["penalty"]) == (points, penalty_minutes):
            rank = rows[-1]["rank"]
        else:
            rank = len(rows) + 1
        rows.append({
            "rank": rank,
            "points": points,
            "penalty": penalty_minutes,
            "party": {
                "participantType": "CONTESTANT",
                "teamId": f"{contest['id']}:{team_id}",
                "teamName": name,
                "university": university.text() if university else "",
                "members": [],
            },
            "problemResults": [parse_domjudge_cell(cell) for cell in problem_cells],
        })
    return {"status": "OK", "result": {"contest": contest, "problems": problems, "rows": rows}}
