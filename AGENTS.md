# Branch rules

- When working on the `tariq` branch, keep all changes on `tariq`.
- Treat `main` as read-only: fetch it and merge its changes into `tariq` when requested.
- Never push anything to `main`, merge `tariq` into `main`, or otherwise modify `main` while working on `tariq`.

# Live preview

- The pm2 process `dolphin-city-ui` runs `preview_ui.py` at http://127.0.0.1:18744, serving the local `index.html` against the hosted game server.
- After every change, make sure that process is online and serving the new code (`pm2 restart dolphin-city-ui` if needed; it also restarts itself when `preview_ui.py` changes).
- `index.html` is read fresh on each request, and open pages on localhost check for a new version every 2 seconds and reload themselves, so do not break the `gameStyles` / `gameScript` ids or the update check at the end of the script.
