# Yorrity SEO Gen

- `main.py`, `server.py`, `assets/`, `build.bat`, `run.bat` - the Windows app source
- `site/index.html` - the single-file website (paste into Odoo)
- `docs/version.json` - update feed, served by GitHub Pages
- `.github/workflows/release.yml` - builds the .exe and creates a GitHub Release when you push a tag like `v1.0.2`

## Release a new version
1. Change the version in `assets/version.json` and `docs/version.json`.
2. Commit, then `git tag v1.0.2 && git push --tags`.
3. GitHub builds `YorritySEOGen.exe` and publishes it under Releases.
