# ICPC Scoreboard

One TV scoreboard for Codeforces, OpenTrains / OpenCup, and DOMjudge.

## Run locally

```bash
python3 server.py
```

Open http://localhost:8080/, choose a data source, and enter its contest or scoreboard URL. No configuration file or API key is required to start the application.

- **Codeforces:** contest ID or contest URL, including `https://codeforces.com/group/GROUP/contest/ID`. Private contests use the server's `pashka-bot` account.
- **OpenTrains:** public HTML standings URL, including Pafos/OpenCup pages.
- **DOMjudge:** public ICPC scoreboard URL or static HTML export.

Settings remember the selected source and its last URL in this browser. The address bar contains a shareable contest link, without API credentials. University aliases are edited under **University names**, stored in this browser, and apply to all sources. Invalid alias JSON is rejected before changing the contest.

The display refreshes every 30 seconds, shows 10 teams per page, and rotates problem groups when necessary. First-to-solve and pending/frozen submissions retain their distinct styles. Opening settings pauses automatic refresh; switching sources cancels the old request and clears old highlights.

## Permanent links

```text
/?source=codeforces&contest=2045
/?source=codeforces&url=https%3A%2F%2Fcodeforces.com%2Fgroup%2FGROUP%2Fcontest%2FID
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
| `CODEFORCES_CONTEST_URL` | Default Codeforces contest URL (takes precedence over contest ID) |
| `CODEFORCES_CONTEST_ID` | Default Codeforces contest ID |
| `CODEFORCES_GROUP_CODE` | Optional group code for the default contest |
| `CODEFORCES_API_KEY` | Server-only API key belonging to `pashka-bot` |
| `CODEFORCES_API_SECRET` | Server-only API secret belonging to `pashka-bot` |
| `UNIVERSITY_ALIASES` | JSON object mapping full university names to display aliases |
| `HOST`, `PORT` | Bind address and port; defaults: `0.0.0.0:8080` |

## Codeforces API and pashka-bot

For the administrator: create a fresh API key and secret for the dedicated **pashka-bot** account, then set `CODEFORCES_API_KEY` and `CODEFORCES_API_SECRET` in Render's **Environment** settings and redeploy. Keep both values on the server; do not put them in browser settings, URLs, committed configuration files, or chat. For local development, provide the same environment variables through your local secret-management setup.

For contest organizers: add **pashka-bot** to your Codeforces group and grant it access to the contest, then paste the group contest URL into the scoreboard settings. Alternatively, enter the contest ID and group code separately. Viewers never need their own API credentials. If Codeforces denies access, check both the group and contest permissions for the bot.

**Publishing boundary:** this service exposes standings accessible to the bot to anyone who supplies the contest ID and group code. Adding the bot is therefore permission to broadcast those standings, not a way to keep them private. Use a dedicated account only in groups intended for this scoreboard. The server never enables `asManager` or forwards arbitrary API methods or caller-supplied credentials.

Regular public contests are requested anonymously with only `contestId`; Gym, mashup, and group contests use server-side authentication when required. Requests are limited to one every 2.1 seconds per server process, with a shared 15-second cache. Only ICPC scoring is supported. See the [Codeforces API documentation](https://codeforces.com/apiHelp/methods) for access rules.

Spectator ranklist URLs are no longer supported. Replace `CODEFORCES_STANDINGS_URL` with `CODEFORCES_CONTEST_URL` (or use `contest_id` and `group_code` in JSON). Legacy personal `api_key` / `api_secret` values in JSON are deliberately ignored, and old browser API credentials are removed on page load. Upstream errors are sanitized so signed URLs and credentials are not returned to viewers. API availability still depends on Codeforces; Cloudflare and rate-limit errors are reported without exposing credentials.

## HTML sources

The OpenTrains adapter reads the OpenCup-style `.standings` table, including first-to-solve and frozen cells.

The DOMjudge adapter has been checked against [the official demo](https://www.domjudge.org/demoweb/public) (version 10 development) and [FSU](https://bastion.cs.fsu.edu/public) (7.3.3). It preserves rank, solved count, penalty, solve time, rejected attempts, first-to-solve, and pending submissions. `1 + 2 tries` means one rejected and two pending attempts, displayed as `?2`. Universities are separate from team names; participant details are not fetched. Team IDs remain stable when ranks change.

Static DOMjudge exports may omit clock metadata; then the clock shows `--:--:--`. Login-protected pages, non-ICPC scoring, and custom HTML layouts are not supported.

HTML fetching accepts only public HTTP/HTTPS URLs on ports 80/443, checks DNS and redirects, connects to validated public IPs, and limits responses to 8 MiB. Local files, embedded URL credentials, loopback, private networks, and cloud metadata addresses are rejected.

## Deploy to Render

`render.yaml` defines a free Python web service named `icpc-scoreboard`. It runs tests before deployment and uses `/health` for readiness. No contest-specific environment variables or secret files are needed to start; authenticated Codeforces contests require the bot credentials described above.

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

Tests cover Codeforces API signing, anonymous and authenticated requests, credential isolation, safe errors, shared caching and rate limiting, DOMjudge versions, freezes, empty tables, stable team IDs, provider selection, and public-URL restrictions. Fixtures omit account/session data from saved pages.

Frontend helper tests and a full-script syntax check can also be run with JavaScriptCore on macOS:

```bash
/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc tests/frontend.test.js
```
