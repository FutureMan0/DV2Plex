# Contributing to DV2Plex

Thanks for helping. Bug reports from real tapes and cameras are as valuable as code: most
of us cannot test every camera, deck or capture card.

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md). Security problems go to
[SECURITY.md](SECURITY.md), not into public issues.

## Reporting a problem

Use the issue forms. The most useful things to include:

- how you run DV2Plex (desktop app, `./run.sh`, the systemd service) and the version
  (Settings → *This installation*)
- your system, the camera or deck, and `ffmpeg -version`
- the log: the Logs tab, or the log file (path in Settings → *This installation*). Tokens
  are masked in it; check it for titles or paths you would rather not share.

## Setting up

You need Python 3.10 or newer, git and ffmpeg. No camera is needed for development.

```bash
git clone https://github.com/FutureMan0/DV2Plex.git
cd DV2Plex
python -m venv .venv
. .venv/bin/activate                  # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt   # enough for the interface, the tests and the demo
python -m dv2plex --demo              # the interface with a simulated camera
```

`requirements.txt` adds Real-ESRGAN (PyTorch), Stable Diffusion and the full poster
generator; you only need them when you work on those parts.

## Checks

The same commands run on every pull request (`.github/workflows/ci.yml`), on Linux,
Windows and macOS:

```bash
python -m pytest            # unit tests and the end-to-end runs with the simulated camera
ruff check                  # errors and likely bugs
mypy                        # types of the reworked modules
python -m dv2plex --demo-run   # capture, merge, upscale, poster, export once, with a report
```

For interface changes also run the browser test and look at the screenshots
(`pip install playwright && python -m playwright install chromium` first):

```bash
python scripts/ui_smoke.py
python scripts/screenshots.py --out /tmp/shots
```

No test may run `sudo`, `systemctl`, `chown` or a real `dvgrab`; `dv2plex/conftest.py` fails
any test that tries. Code that talks to dvgrab is tested against `dv2plex/fake_dvgrab.py`.

## Making a change

- Branch from `master`, one topic per pull request.
- Keep the behaviour of the existing steps unless the pull request is about changing it.
- Tests for what you fix or add; a bug fix comes with the test that failed before.
- Interface texts go into `dv2plex/web/i18n.json`, in English and German
  (`test_interface.py` checks that both have every key). Set text with `textContent`, never
  `innerHTML`.
- Update the documentation and `CHANGELOG.md` (under the coming version) in the same pull
  request.
- Commit messages in English, imperative, a short first line ("Keep the aspect of 16:9
  tapes"), the why in the body.

## Releases

Versions follow [Semantic Versioning](https://semver.org/). To release, a maintainer sets
`__version__` in `dv2plex/__init__.py`, moves the `CHANGELOG.md` entries under that version,
and pushes a tag `v<version>`. The release workflow builds the desktop app for Windows,
macOS and Linux, runs it once end to end, and creates a draft release with the packages and
the changelog section; the maintainer reviews and publishes it.
