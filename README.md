# ICPC Scoreboard

One TV scoreboard for Codeforces, OpenTrains / OpenCup, and DOMjudge.

## Run locally

```bash
python3 server.py
```

Open http://localhost:8080/, choose a data source, and enter its contest or scoreboard URL. No configuration file or API key is required to start the application.

- **Codeforces:** spectator ranklist URL (`https://codeforces.com/spectator/ranklist/...`). No API keys.
- **OpenTrains:** public HTML standings URL, including Pafos/OpenCup pages.
- **DOMjudge:** public ICPC scoreboard URL or static HTML export.

Settings remember the selected source and its last URL in this browser. The address bar contains a shareable contest link. A Codeforces spectator token grants access to its ranklist, so share this link only with its intended audience. University aliases are edited under **University names**, stored in this browser, and apply to all sources. Invalid alias JSON is rejected before changing the contest.

The display refreshes every 30 seconds, shows 10 teams per page, and rotates problem groups when necessary. First-to-solve and pending/frozen submissions retain their distinct styles. Opening settings pauses automatic refresh; switching sources cancels the old request and clears old highlights.

## Permanent links

```text
/?source=codeforces&url=https%3A%2F%2Fcodeforces.com%2Fspectator%2Franklist%2Fyour-ranklist-token
/?source=opentrains&url=https%3A%2F%2Fpafos25.opencup.org%2Fresday8
/?source=domjudge&url=https%3A%2F%2Fwww.domjudge.org%2Fdemoweb%2Fpublic
```

Legacy `source=opencup`, `opencup_url`, and `OPENCUP_STANDINGS_URL` remain supported.

## Optional server defaults

Configuration is optional. Set defaults in the git-ignored `scoreboard.config.json`, or select a file with `SCOREBOARD_CONFIG`:

```bash
SCOREBOARD_CONFIG=examples/scoreboard.config.domjudge.example.json python3 server.py
```

Examples are available for `codeforces`, `opentrains`, and `domjudge` in `examples/scoreboard.config.<source>.example.json`. The older OpenCup example remains compatible.

Environment variables override file values:

| Variable | Purpose |
| --- | --- |
| `SCOREBOARD_SOURCE` | Default source: `codeforces`, `opentrains`, or `domjudge` |
| `OPENTRAINS_STANDINGS_URL` | Default OpenTrains URL |
| `DOMJUDGE_STANDINGS_URL` | Default DOMjudge URL |
| `CODEFORCES_STANDINGS_URL` | Default Codeforces spectator ranklist URL |
| `UNIVERSITY_ALIASES` | JSON object mapping full university names to display aliases |
| `HOST`, `PORT` | Bind address and port; defaults: `0.0.0.0:8080` |

## Codeforces spectator ranklists

Create a spectator ranklist on Codeforces and paste its viewer URL into the Codeforces settings. The server reads the HTML table directly, without API calls, API keys, account cookies, or group-manager access. Team names and member handles come from separate links; solved counts, penalties, rejected attempts, and solve times come from table cells. Only ICPC scoring is supported. The countdown shows **Time remaining**, since this page does not provide the contest start time or duration. First-to-solve is not inferred from a potentially filtered ranklist.

Old contest-ID links and `CODEFORCES_API_KEY`, `CODEFORCES_API_SECRET`, `CODEFORCES_CONTEST_ID`, and `CODEFORCES_GROUP_CODE` settings are no longer used. Replace them with `CODEFORCES_STANDINGS_URL` (or `codeforces_url` in JSON). Previously saved browser API credentials are removed on page load.

Codeforces may block server-side HTML requests with Cloudflare HTTP 403. The app reports that explicitly; opening the page in a browser does not authorize Render's separate requests. The parser has been verified against a saved spectator page, but parsing support does not bypass this upstream access restriction. Frozen `?` / `?N` notation is covered by synthetic tests; the supplied real snapshot was not frozen.

## HTML sources

The OpenTrains adapter reads the OpenCup-style `.standings` table, including first-to-solve and frozen cells.

The DOMjudge adapter has been checked against [the official demo](https://www.domjudge.org/demoweb/public) (version 10 development) and [FSU](https://bastion.cs.fsu.edu/public) (7.3.3). It preserves rank, solved count, penalty, solve time, rejected attempts, first-to-solve, and pending submissions. `1 + 2 tries` means one rejected and two pending attempts, displayed as `?2`. Universities are separate from team names; participant details are not fetched. Team IDs remain stable when ranks change.

Static DOMjudge exports may omit clock metadata; then the clock shows `--:--:--`. Login-protected pages, non-ICPC scoring, and custom HTML layouts are not supported.

HTML fetching accepts only public HTTP/HTTPS URLs on ports 80/443, checks DNS and redirects, connects to validated public IPs, and limits responses to 8 MiB. Local files, embedded URL credentials, loopback, private networks, and cloud metadata addresses are rejected.

## Deploy to Render

`render.yaml` defines a free Python web service named `icpc-scoreboard`. It runs tests before deployment and uses `/health` for readiness. No contest-specific environment variables or secret files are needed.

Create a Render Web Service from this repository:

- Build: `python3 -m unittest discover -s tests -v`
- Start: `python3 server.py`
- Health check: `/health`
- Instance type: Free
- Name: `icpc-scoreboard`

Render supplies `PORT`. The requested address is https://icpc-scoreboard.onrender.com/ (subject to name availability). Free services can take a while to wake after inactivity.

For fixed-contest deployments, provider-specific Blueprint examples are also available in `examples/render.<source>.yaml`.

### University names on Render

In the Render dashboard, open the service's **Environment** settings and add
`UNIVERSITY_ALIASES` with a JSON object as its value (no surrounding shell quotes):

```json
{
  "Delft University of Technology": "TU Delft",
  "National Technical University of Athens": "NTUA",
  "National and Kapodistrian University of Athens": "NKUA",
  "Aristotle University of Thessaloniki": "AUTH",
  "American University of Beirut - Mediterraneo": "AUB Mediterraneo",
  "Neapolis University Pafos": "NUP"
}
```

Save the environment changes and redeploy, then reload the scoreboard page.
Names must match the source's full university names exactly. These defaults
apply to every source, including links with `?source=...&url=...`.
Browser settings override individual names, not the entire server dictionary.
Saving browser settings stores only differences from the server defaults, so
unchanged defaults can receive future updates from Render. To reset a local
override, remove its entry in **University names** and save.

## Add a source

Providers are registered in `server.py` through `STANDINGS_SOURCES`. Each adapter supplies public defaults, URL-query settings, and a fetch function returning `(status, content_type, payload_bytes)`. Parsers return the common `contest`, `problems`, and `rows` shape. Add a matching option and label to the setup form for a new provider.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Fixtures cover Codeforces spectator HTML, DOMjudge versions, freezes, empty tables, stable team IDs, provider selection, and public-URL restrictions. Fixtures omit account/session data from saved pages.

Frontend helper tests and a full-script syntax check can also be run with JavaScriptCore on macOS:

```bash
/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc tests/frontend.test.js
```
