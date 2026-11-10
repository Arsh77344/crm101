# Commerce Business OS

Internal team-test build of a local commerce operations platform.

The new **Sell → Launch a product** workspace prepares phone photos, brand-aware copy, colour/size variants, market-price suggestions, reviewed store listings and social kits. See [the product launch guide](docs/PRODUCT_LAUNCH.md) for setup, supported connections and validation limits.

## Getting started

Python 3.12 or newer is required. Install the dependencies and run the launcher for your platform:

```bash
python3 -m pip install -r app/requirements-team.txt
./START_APP.sh
```

For macOS, double-click `START_APP.command`; on Windows, run `START_APP.bat`.

On the first launch, the app creates `data/FIRST_RUN_CREDENTIALS.txt` locally. It is intentionally excluded from version control.

See [README_FIRST.md](README_FIRST.md) for build information and [docs/QUICK_START.md](docs/QUICK_START.md) for usage guidance.

## Develop and preview on GitHub (Codespaces)

1. On the repo page choose **Code → Codespaces → Create codespace on main**.
2. The app installs its requirements and starts itself; the **CRM** port (8765) opens in a preview pane beside the editor.
3. Sign in with the Owner credentials in `data/FIRST_RUN_CREDENTIALS.txt`.
4. Edit files, then restart with `pkill -f team_start.py; sh START_APP.sh &` and reload the preview.
5. Commit and push from the Source Control panel. Going live later needs a host (for example Render or Railway) because GitHub Pages cannot run Python.
