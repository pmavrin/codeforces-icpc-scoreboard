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

## Security

- `scoreboard.config.json` is git-ignored and should remain readable only by the server account.
- The server only exposes `/`, `/index.html`, and `/api/standings`; it does not serve the config file or arbitrary workspace files.
- The proxy is locked to the configured contest and group, so it cannot be used to query other private contests.
- The API secret is used only to calculate Codeforces request signatures and is never returned to browsers.

Static hosting still works for public contests. Private group contests on static hosting fall back to the credential form in `index.html`.
