# Security

## Supported versions

Security fixes go into the latest release. Please update before you report.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private reporting instead:
**Security → Report a vulnerability** on
[github.com/FutureMan0/DV2Plex](https://github.com/FutureMan0/DV2Plex/security/advisories/new).
Describe what an attacker can do, on which setup (desktop app, server on `127.0.0.1`, server on
the network), and how to reproduce it. You get an answer within two weeks.

## How DV2Plex protects itself, and where it does not

- **On `127.0.0.1`** (the default) only programs on the same machine reach the server. It
  answers only to this machine's host names, and it refuses changes coming from other web
  pages (Origin check), so a website you visit cannot drive it.
- **On the network** (`--host 0.0.0.0`, `server.host`) every API request needs the API token.
  The server speaks plain HTTP: anyone who can read the traffic can read the token. Use it on
  networks you trust, behind a reverse proxy with HTTPS, or through an SSH tunnel.
- **One token, full control.** Whoever has it can do everything the interface can, including
  `sudo chown` on a folder and an update. There are no user accounts.
- **Root.** On Linux dvgrab needs access to `/dev/raw1394`; `./run.sh --no-gui` runs the whole
  server as root for that. A udev rule for the FireWire device and running as a normal user is
  safer.
- **Files.** The routes that read or write films accept only paths inside the import folder;
  the folder browser (token required) lists any folder the server can read.
- **Updates.** Git installations update from the branch they were cloned from, if
  `update.enabled` is on (off by default). The desktop app only shows a link to new releases
  and does not install anything by itself. The builds are not signed.
