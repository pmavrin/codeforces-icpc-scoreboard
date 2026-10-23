# ICPC Scoreboard

One TV scoreboard for Codeforces, OpenTrains / OpenCup, and DOMjudge.

## Run locally

```bash
python3 server.py
```

Open http://localhost:8080/, choose a data source, and enter its contest or scoreboard URL. No configuration file or API key is required to start the application.

- **Codeforces:** contest ID or URL, optional group code, and private/Gym credentials.
- **OpenTrains:** public HTML standings URL, including Pafos/OpenCup pages.
- **DOMjudge:** public ICPC scoreboard URL or static HTML export.

Settings remember the selected source and its last URL in this browser. The address bar contains a shareable contest link. API secrets are never included in that link. University aliases are edited under **University names**, stored in this browser, and apply to all sources. Invalid alias JSON is rejected before changing the contest.

The display refreshes every 30 seconds, shows 10 teams per page, and rotates problem groups when necessary. First-to-solve and pending/frozen submissions retain their distinct styles. Opening settings pauses automatic refresh; switching sources cancels the old request and clears old highlights.

## Permanent links

```text
/?source=codeforces&contest=2045
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
| `CODEFORCES_CONTEST_ID` | Default Codeforces contest |
| `CODEFORCES_GROUP_CODE` | Default Codeforces group |
| `CODEFORCES_API_KEY`, `CODEFORCES_API_SECRET` | Optional server credentials, restricted to the configured contest and group |
| `UNIVERSITY_ALIASES` | JSON object mapping full university names to display aliases |
| `HOST`, `PORT` | Bind address and port; defaults: `0.0.0.0:8080` |

## Codeforces authentication

Public contests use the anonymous API through the server, with a direct-browser fallback if necessary. Private and Gym contests can use API credentials entered in settings; the browser signs those requests and sends them directly to Codeforces. Credentials stay in session storage unless **Remember credentials on this display** is checked.

Alternatively, configure server credentials for a particular contest and group. Those credentials can never be used to query a different contest through this server. Public deployments do not need server credentials.

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

## Add a source

Providers are registered in `server.py` through `STANDINGS_SOURCES`. Each adapter supplies public defaults, URL-query settings, and a fetch function returning `(status, content_type, payload_bytes)`. Parsers return the common `contest`, `problems`, and `rows` shape. Add a matching option and label to the setup form for a new provider.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Fixtures cover DOMjudge versions, freezes, empty tables, stable team IDs, provider selection, credential boundaries, and public-URL restrictions.
