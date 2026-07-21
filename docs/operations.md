# Operations and maintenance

This guide covers the parts of TBC that keep recordings, integrations, and the application itself
healthy after cameras have been added.

## Storage destinations

Recording destinations are configured under **Storage → Destinations**.

- **Local or mounted path:** a directory visible inside the TBC container. The standard Docker
  deployment mounts `/recordings`; Home Assistant uses `/recordings/tbc-camera-manager` inside the
  app for its media directory.
- **S3-compatible storage:** endpoint, region, bucket, prefix, access key, and secret key. Secrets
  are encrypted at rest and never returned by the external API.

A camera can select a destination for continuous and event recording. “First available
destination” follows the configured destination order. Removing a destination does not delete
recording files already stored outside the database.

## Retention and storage explorer

Retention rules can match a camera and event type and apply a maximum age, maximum size, or both.
Locked clips are excluded. Cleanup also runs in the background; use **Storage → Explorer** to view
space usage, preview cleanup candidates, and start cleanup manually.

The database stores recording metadata separately from the media. Back up or migrate both when the
recording archive itself must be preserved.

## Notifications

Notification channels can be filtered by event name and may attach a snapshot. Supported channel
types include generic webhooks, Telegram, email/SMTP, Pushover, Home Assistant Notify, ntfy, and
Gotify. Required URL, token, chat, service, or SMTP fields depend on the selected type.

Set `TBC_PUBLIC_BASE_URL` when notification payloads must contain externally reachable links.
Keep channel tokens and SMTP passwords restricted; they are encrypted in the database but a
notification provider still receives the data sent to it.

## MQTT and Home Assistant

The MQTT page configures broker host, port, credentials, topic prefix, discovery prefix, and Home
Assistant Discovery. TBC publishes supported camera state and detection events and can expose
controls where implemented. With Home Assistant OS, the Mosquitto app is commonly reachable as
`core-mosquitto:1883` from the app network.

The separate TBC Home Assistant integration uses the external API. Create a dedicated named token
and grant control scope only when the integration needs to change settings or start streams. See
[api.md](api.md).

## Health monitoring and debug log

**Operations → Performance** shows CPU and memory usage plus health states and state-change events
for monitored components. Refreshing performs the checks immediately; regular checks also run in
the background.

Administrators can open the debug-log drawer from the footer or **Settings**. It collects current
application and ffmpeg live-process messages and can be cleared without deleting recordings or
audit events. Operational logs may contain hosts, camera names, or provider errors; review them
before sharing publicly.

## Backup and restore

**Settings → Backup & restore** creates an encrypted archive of the SQLite database, including
cameras, users, settings, cloud/network accounts, and API-token metadata. The archive is stored
locally in `TBC_BACKUPS_PATH` (default `/data/backups`) and can be downloaded from the backup list.
Its filename is `TBC_v<version>_<date>-<time>.tbcbackup`, for example
`TBC_v0.8.1_2026-07-21-09-49-28.tbcbackup`. Stored credentials stay encrypted with the current
`TBC_SECRET_KEY`.

Restore requirements:

1. The target instance must use the same `TBC_SECRET_KEY` as the source.
2. Restoring replaces the active database; TBC creates a `.bak` copy first.
3. Restart TBC after a successful restore.
4. Media files, plugin packages, downloaded models, and theme assets are not all contained in the
   database archive and need separate persistence or backup when required.

Losing `TBC_SECRET_KEY` makes encrypted credentials and compatible backup restoration unusable.
Store it in a password manager or deployment secret store.

## Audit log

The audit log records security- and configuration-relevant actions with time, user, target, IP
address, and detail. Actions performed through a named API token are attributed to
`api-token:<token name>`. Use filters to investigate changes without relying on the transient debug
log.

## Application and plugin updates

TBC checks GitHub releases and registered plugin sources hourly.

- **Application updates** are notifications only. Pull or rebuild the container image/checkout;
  TBC intentionally does not self-update with one click.
- **Plugin-source updates** compare the installed commit with the configured branch or tag. An
  administrator can synchronize an available update after reviewing its source.
- Imported ZIP plugins are not tied to a repository and therefore have no automatic source update
  check.

Installed plugins execute with the privileges of the TBC process. Update from trusted repositories
and use the bundled plugin tests as an additional check, not as a security boundary.

If a plugin (its own or a newly synced update's) declares Python packages TBC does not already
have installed, **Synchronize**/**Update now**/**Install directly** stops and redirects to a
confirmation page listing exactly what is missing instead of failing later with an opaque
error. Nothing installs until **Install now** is clicked explicitly; see
[**Plugin-declared pip requirements**](plugin-sources.md#plugin-declared-pip-requirements-requirements)
in plugin-sources.md.

## Security checklist

- Replace the default administrator password and `TBC_SECRET_KEY` before exposing TBC.
- Use HTTPS at a reverse proxy and set `TBC_COOKIE_SECURE=true` for HTTPS-only deployments.
- Keep the web UI, camera networks, RTSP, ONVIF, MQTT, WebRTC port `8555`, and storage endpoints
  restricted to trusted networks.
- Prefer one API token per integration, read-only by default, and revoke tokens that are no longer
  used.
- Only install trusted camera, cloud, and network plugins; they contain executable Python code.
- Back up the database, secret key, plugin/theme directories, and recording media according to the
  recovery level you need.
- Review viewer camera assignments and the audit log regularly.
