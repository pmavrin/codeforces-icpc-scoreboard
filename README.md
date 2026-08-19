# ICPC TV Scoreboard

The included Python server keeps Codeforces API credentials off the TV and signs group-contest requests server-side.

## Start the display

1. Configure `scoreboard.config.json`. Safe templates are available in `examples/scoreboard.config.codeforces.example.json` for Codeforces and `examples/scoreboard.config.opencup.example.json` for OpenCup.
2. Start the server:

   ```bash
   python3 server.py
   ```

3. On the TV, open:

   ```text
   http://SERVER_IP:8080/
   ```

The configured contest opens immediately and refreshes every 30 seconds. No contest or credential entry is needed on the TV. The first standings page stays visible for two minutes; subsequent pages rotate every 30 seconds.
The table adapts to the screen width; when a contest has more problem columns than can remain readable, it automatically rotates through labeled problem groups while keeping rank, team, solved, and penalty visible.

## Use an OpenCup standings page

The same display can read an OpenCup-style HTML standings page, for example `https://pafos25.opencup.org/resday8`.
Copy `examples/scoreboard.config.opencup.example.json` to `scoreboard.config.json` or set these values:

```json
{
  "source": "opencup",
  "opencup_url": "https://pafos25.opencup.org/resday8",
  "university_aliases": {
    "Delft University of Technology": "TU Delft",
    "Kharkiv National University of Radio Electronics": "KNURE",
    "University of Wroclaw": "UWr"
  },
  "host": "0.0.0.0",
  "port": 8080
}
```

Then start the server as usual. The server fetches the HTML page, parses the `.standings` table, and serves it to the existing TV UI through `/api/standings`.
For team names shaped like `<university>: <team name> (participants)`, the display shows `<short university>: <team name>` on the main line and participants below it. Add more entries to `university_aliases` when a university needs a shorter on-screen name.

## Add another judging system

Standings providers are registered in `server.py` through `STANDINGS_SOURCES`. A new provider needs:

- a parser or API client that returns the same standings shape as Codeforces: `contest`, `problems`, and `rows`;
- a `public_config` function for non-secret browser settings such as `source` and `sourceLabel`;
- a `fetch` function that returns `(status, content_type, payload_bytes)`;
- one entry in `STANDINGS_SOURCES`.

The browser already renders that shared shape, so most new systems should only need server-side adapter code.

## Deploy on Render

The repository includes a Render Blueprint in `render.yaml`. It is ready for the Pafos/OpenCup standings page by default.

1. Push the repository to GitHub, GitLab, or Bitbucket. Do not add `scoreboard.config.json`.
2. In the [Render Dashboard](https://dashboard.render.com/), choose **New → Blueprint** and connect the repository.
3. Create the Blueprint and wait for the health check to pass.
4. Open the generated `https://…onrender.com/` URL on the TV.

The default `render.yaml` configures:

- `SCOREBOARD_SOURCE=opencup`
- `OPENCUP_STANDINGS_URL=https://pafos25.opencup.org/resday8`
- `UNIVERSITY_ALIASES` for the universities currently present in that standings page
- the Python start command and `/health` check

For a Codeforces deployment, use `examples/render.codeforces.yaml` as the starting point for `render.yaml`. During the Blueprint setup, Render will ask for `CODEFORCES_API_KEY` and `CODEFORCES_API_SECRET`; set `CODEFORCES_CONTEST_ID` and `CODEFORCES_GROUP_CODE` for the target contest.

Additional Render Blueprint examples are available in:

- `examples/render.opencup.yaml`
- `examples/render.codeforces.yaml`

Render supplies `PORT` automatically. The server also supports the following environment variables, which take precedence over `scoreboard.config.json`:

| Variable | Purpose |
| --- | --- |
| `CODEFORCES_API_KEY` | Codeforces API key owned by a group manager |
| `CODEFORCES_API_SECRET` | Matching Codeforces API secret |
| `CODEFORCES_CONTEST_ID` | Contest ID |
| `CODEFORCES_GROUP_CODE` | Group code |
| `SCOREBOARD_SOURCE` | `codeforces` or `opencup`; defaults to `codeforces` |
| `OPENCUP_STANDINGS_URL` | OpenCup HTML standings URL when `SCOREBOARD_SOURCE=opencup` |
| `UNIVERSITY_ALIASES` | Optional JSON object mapping full university names to display aliases |
| `PORT` | HTTP port; supplied by Render |
| `HOST` | Bind address; defaults to `0.0.0.0` |

## Security

- `scoreboard.config.json` is git-ignored and should remain readable only by the server account.
- The server only exposes `/`, `/index.html`, `/health`, and `/api/standings`; it does not serve the config file or arbitrary workspace files.
- The proxy is locked to the configured contest and group, so it cannot be used to query other private contests.
- The API secret is used only to calculate Codeforces request signatures and is never returned to browsers.

Static hosting still works for public contests. Private group contests on static hosting fall back to the credential form in `index.html`.
