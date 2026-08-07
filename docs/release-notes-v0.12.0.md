# TBC 0.12.0 - Search, store & detect

## Highlights

- Added optional semantic clip search. Enable it under **Admin -> AI detection** to search
  recordings with natural language such as "silver van in the driveway". The default CLIP model
  is downloaded on first use (about 600 MB), and existing recordings are indexed gradually in the
  background.
- Local AI events now retain the specific animal or vehicle type, such as `cat` or `truck`.
  Vehicle events also receive a best-effort dominant colour derived from the snapshot. Both are
  visible and filterable on the **Clips** page.
- Added WebDAV storage for event recordings, continuous-recording segments, and automated backups.
  Playback and downloads are securely proxied through TBC because WebDAV has no presigned URL.
- Added Slack, Discord, Matrix, and Signal notification channels. Signal uses a self-hosted
  `signal-cli-rest-api` instance; Slack and Discord can include a linked snapshot when
  `TBC_PUBLIC_BASE_URL` is configured.
- Added an experimental Hailo-8/8L local-AI backend for standalone deployments. It requires a
  manually built `Dockerfile.hailo` image, an account-gated HailoRT wheel, compatible hardware,
  and a user-supplied `.hef` model with metadata. It has not been validated against physical Hailo
  hardware in this project.

## Upgrade notes

- Existing SQLite databases migrate automatically, including the new WebDAV and recording-metadata
  fields.
- Semantic search is disabled by default and does not download its model until enabled.
- SMB/CIFS and NFS remain "Local or mounted path" destinations: mount the share into the container
  and use that path as the storage destination.

## Full changelog

https://github.com/404GamerNotFound/TBC-camera-manager/compare/v0.11.0...v0.12.0
