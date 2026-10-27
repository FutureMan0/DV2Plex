# Upgrading a running installation to 2.0

For servers that run DV2Plex from a git checkout (the `dv2plex` systemd service that
`setup.sh` installs). The desktop app is installed fresh and needs none of this.

## What changes when 2.0 arrives

| | Before | After 2.0 |
| :-- | :-- | :-- |
| Listens on | all interfaces (`0.0.0.0:5000`) | `127.0.0.1:5000` only |
| Access from other machines | open | needs the API token |
| Settings file | `dv2plex/config/settings.json` (tracked by git) | `dv2plex/config/settings.local.json` (yours, ignored by git) |
| Automatic updates | on | off for new installations; yours keeps its setting |

On its first start, 2.0 copies your `settings.json` to `settings.local.json` if you had
changed it, creates an API token and saves it there.

**After the update the web interface is no longer reachable from other machines** until you
do one of the two things below.

## Keep reaching it over the network

On the server:

```bash
cd /path/to/DV2Plex                      # the folder of the service
sudo ./venv/bin/python -m dv2plex --show-token
```

Then tell DV2Plex to listen on the network, either in the settings

```bash
sudo nano dv2plex/config/settings.local.json     # "server": { "host": "0.0.0.0", ... }
```

or in the service (`/etc/systemd/system/dv2plex.service`, `ExecStart=… ./run.sh --no-gui --host 0.0.0.0`,
then `sudo systemctl daemon-reload`). Restart it:

```bash
sudo systemctl restart dv2plex
```

Open `http://<server>:5000/?token=<token>` once in each browser; it keeps the token.

Or leave it on `127.0.0.1` and use an SSH tunnel: `ssh -L 5000:localhost:5000 user@server`,
then `http://localhost:5000`. The token travels unencrypted over plain HTTP, so on networks
you do not trust the tunnel is the better choice.

## If the automatic update did not happen

Installations whose service runs as root in a checkout owned by another user never updated:
git refused with "detected dubious ownership" (2.0 fixes that, but only once it is
installed). Update by hand:

```bash
cd /path/to/DV2Plex
sudo -u <owner of the folder> git pull
sudo systemctl restart dv2plex
```

If git stops because of local changes to `dv2plex/config/settings.json`, keep your settings first:

```bash
cp -n dv2plex/config/settings.json dv2plex/config/settings.local.json
git checkout -- dv2plex/config/settings.json
git pull
```

## Later: `settings.json` leaves the repository

A later release removes `dv2plex/config/settings.json` from git. 2.0's updater resets that
file before it pulls, so the removal goes through; your settings are in
`settings.local.json` by then. Installations that skip 2.0 and jump straight to that
release need the three commands above.

## Other changes you may notice

- Upscaled films keep the tape's shape: 4:3 tapes become 2880 × 2160 instead of a stretched
  3840 × 2160 (see [UPSCALING.md](UPSCALING.md)).
- DV is deinterlaced before upscaling; `"deinterlace": false` in a profile turns that off.
- `capture.auto_postprocess` now does what it says: after the merge the film is upscaled
  (and exported, if `auto_export` is on). Check the setting if you had switched it on and
  forgotten about it.
- Real-ESRGAN profiles show as unavailable when PyTorch is missing.
