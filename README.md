# ICPC TV Scoreboard

The included Python server keeps Codeforces API credentials off the TV and signs group-contest requests server-side.

## Start the display

1. Configure `scoreboard.config.json`. A safe template is available in `scoreboard.config.example.json`.
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

## Deploy on Render

The repository includes a Render Blueprint in `render.yaml`.

1. Push the repository to GitHub, GitLab, or Bitbucket. Do not add `scoreboard.config.json`.
2. In the [Render Dashboard](https://dashboard.render.com/), choose **New → Blueprint** and connect the repository.
3. During the initial Blueprint setup, enter these secret values when prompted:
   - `CODEFORCES_API_KEY`
   - `CODEFORCES_API_SECRET`
4. Create the Blueprint and wait for the health check to pass.
5. Open the generated `https://…onrender.com/` URL on the TV.

The Blueprint already configures contest `620457`, group `NLXJakpbHN`, the start command, and `/health`. Change `CODEFORCES_CONTEST_ID` or `CODEFORCES_GROUP_CODE` in `render.yaml` before deploying a different contest.

Render supplies `PORT` automatically. The server also supports the following environment variables, which take precedence over `scoreboard.config.json`:

| Variable | Purpose |
| --- | --- |
| `CODEFORCES_API_KEY` | Codeforces API key owned by a group manager |
| `CODEFORCES_API_SECRET` | Matching Codeforces API secret |
| `CODEFORCES_CONTEST_ID` | Contest ID |
| `CODEFORCES_GROUP_CODE` | Group code |
| `PORT` | HTTP port; supplied by Render |
| `HOST` | Bind address; defaults to `0.0.0.0` |

## Security

- `scoreboard.config.json` is git-ignored and should remain readable only by the server account.
- The server only exposes `/`, `/index.html`, `/health`, and `/api/standings`; it does not serve the config file or arbitrary workspace files.
- The proxy is locked to the configured contest and group, so it cannot be used to query other private contests.
- The API secret is used only to calculate Codeforces request signatures and is never returned to browsers.

Static hosting still works for public contests. Private group contests on static hosting fall back to the credential form in `index.html`.
