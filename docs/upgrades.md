# Upgrades

## New releases

Once a day the worker asks GitHub for the latest release of this project (the repository in
`GLASSHAUS_SOURCE_URL`). Only the version number and release notes come back; nothing about your server
is sent. When a release is newer than the one running, owners and admins get one notification, and
**Admin → Updates** shows what's new. **Check now** asks again (at most once a minute). Turn the daily
check off with `GLASSHAUS_UPDATE_CHECK=false`.

Updates are server-wide, so the page is only shown when the server hosts a single organization.

## Upgrading from the terminal

```bash
sudo ./update.sh
```

`update.sh` backs up the database, fetches and builds (or with `--pull`, downloads) the new version, tries
it on a copy of the database first, then upgrades; if anything fails it goes back to the running version.
See [Upgrading](../README.md#upgrading).

## Upgrading from the app

The app runs in containers and can't run `update.sh` itself. A small helper on the server does it for
you:

1. Set it up once, in the Glasshaus folder on the server:

   ```bash
   sudo ./scripts/upgrade-agent.sh --install
   ```

   On most Linux servers this adds `/etc/cron.d/glasshaus-upgrade` (every minute, as root). On TrueNAS,
   whose `/etc` is replaced on system updates, it prints a **Cron Job** to add instead (System → Advanced
   Settings → Cron Jobs: the command it shows, run as root, every minute).
2. **Admin → Updates** shows "helper connected" within a minute.
3. When a new release is out, an owner presses **Upgrade to x.y.z** and confirms. Within a minute the
   helper runs `update.sh` (backup, check on a copy, upgrade, health check, roll back on failure). The page
   shows progress and the log; Glasshaus is unavailable for about a minute while it restarts. Reload the
   page when it says the upgrade is done.

### How it is kept safe

- Only **owners**, signed in to the web app, can start an upgrade (not API tokens), and only to the latest
  release. Each request is recorded in the audit log (`system.upgrade_requested`).
- The app can only leave a request in the upgrade folder (`GLASSHAUS_UPGRADE_FOLDER`, `./upgrade` by
  default; owned by uid 10001, mode 770). It never gets Docker or root access. The helper reads only a
  request id and a version number from it, checks both, and runs `update.sh`, which always takes the
  release from your git checkout.
- One upgrade runs at a time. The helper checks in every minute; if it stops, the page says so and the
  button is hidden.
- Extra `update.sh` options for app-started upgrades go in `.env` as `GLASSHAUS_UPGRADE_ARGS` (only
  `--pull` and `--skip-preflight` are accepted).

### Files in the upgrade folder

| File | Written by | Content |
| --- | --- | --- |
| `request.json` | the app | An owner's request (id, version, who, when); removed when the helper starts. |
| `agent.json` | the helper | When it last checked in. |
| `status.json` | the helper | The running or last upgrade: state, versions, times, message. |
| `upgrade.log` | the helper | `update.sh` output (owners see the end of it on the page). |

To stop app-started upgrades, remove the cron job (or `/etc/cron.d/glasshaus-upgrade`).
