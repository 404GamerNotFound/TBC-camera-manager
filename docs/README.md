# TBC documentation

This directory contains the user, operator, integration, and extension-development
documentation for TBC Camera Manager. In a running TBC instance the same files are available
from the **Docs** link in the footer; Markdown links between documents stay inside the web
viewer.

## Using TBC

- [User guide](user-guide.md) - cameras, dashboard, live view, recordings, archives, local AI,
  recognition, controls, network mappings, and user roles.
- [Operations and maintenance](operations.md) - storage, retention, notifications, MQTT,
  monitoring, backups, audit log, updates, and security.
- [Deployment and configuration](deployment.md) - Docker, Home Assistant, persistent paths,
  ports, environment variables, upgrades, and troubleshooting.

## Integrations

- [External API](api.md) - API tokens, read endpoints, control-scoped endpoints, and HLS access.
- [AI interface (MCP)](mcp.md) - connecting an MCP-capable AI client to TBC.

## Plugin and theme development

- [Camera modules](camera-modules.md) - camera discovery, streams, recording, controls, firmware,
  and plugin-specific AI models.
- [Cloud accounts](cloud-accounts.md) - account forms, verification flows, and cloud device
  discovery.
- [Network providers](network-accounts.md) - controller accounts, device status, and camera-to-MAC
  mappings.
- [Design themes](design-themes.md) - theme manifests, stylesheets, assets, and activation.
- [Plugin tests and external sources](plugin-sources.md) - repository installation, validation,
  tests, synchronization, update detection, and a plugin's own pip requirements.

## Documentation conventions

The documents describe the current source tree. Paths and environment variables are shown in
`code style`; menu paths use **bold labels** or arrows such as `Admin → Settings`. Features that
depend on a camera, plugin, storage backend, or optional service only appear in the web interface
when that capability is available.
