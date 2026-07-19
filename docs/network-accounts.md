# Developing network providers

TBC separates camera protocols ([camera-modules.md](camera-modules.md)) and cloud accounts
([cloud-accounts.md](cloud-accounts.md)) from network providers. A network account signs in to
one network controller (a router, switch controller, or similar) and lists the clients it
currently sees, so a camera can be mapped by MAC address to show live connectivity status:
online/offline, wired vs. Wi-Fi, which access point or switch it is connected through, and
signal strength. A network provider never touches video or camera control - that stays with
whatever camera module the camera itself uses.

The mapping between a camera and a network device is stored directly on the camera
(`cameras.network_account_id`, `cameras.network_device_mac`) rather than being discarded after
use, unlike a cloud-account camera import: the whole point is to keep showing live status on
the camera's **Network** tab, not just to import something once.

## Plugin file and account form

A network-plugin ZIP follows the same layout as a camera- or cloud-plugin ZIP: files reside
directly at the archive root or inside exactly one common directory, with `manifest.json` as
the authoritative configuration:

```json
{
  "schema_version": 1,
  "key": "acme_network",
  "label": "Acme Network",
  "version": "1.0.0",
  "description": "Acme network controller",
  "entrypoint": "plugin.py",
  "account_fields": [
    {
      "key": "host",
      "label": "Host",
      "type": "text",
      "required": true,
      "placeholder": "192.168.1.1"
    },
    {
      "key": "identifier",
      "label": "Username",
      "type": "text",
      "required": true,
      "autocomplete": "username"
    },
    {
      "key": "secret",
      "label": "Password",
      "type": "password",
      "required": true,
      "autocomplete": "current-password"
    }
  ]
}
```

`account_fields` is the complete, plugin-supplied description of the account form; the main
project has no knowledge of provider-specific fields. Supported types are `text`, `email`,
`password`, `number`, `checkbox`, and `select`. Every field may define `required`,
`placeholder`, `help_text`, `autocomplete`, `default`, `min`, `max`, and `full_width`; select
fields may also define `options`. Keys may contain lowercase letters, numbers, and
underscores. Unlike cloud accounts, there is no `transient` field concept here - network
provider logins do not need a verification-code flow.

Built-in plugins are completely contained in `app/tbc/network_plugins/<key>/`. None ship
built in today - unlike ONVIF for cameras, there is no vendor-neutral network-controller
protocol to fall back to, so every network provider is an installed plugin.

## Public contract

A network plugin inherits from `tbc_network_api.NetworkAccountModule`:

```python
from tbc_network_api import NetworkAccountModule, NetworkConnectionError, NetworkDevice


class AcmeNetworkModule(NetworkAccountModule):
    async def discover_devices(self, account: dict) -> list[NetworkDevice]:
        host = account.get("host")
        if not host:
            raise NetworkConnectionError("Host is required")
        return [
            NetworkDevice(
                mac_address="aa:bb:cc:dd:ee:ff",
                name="Front door camera",
                ip_address="192.168.1.50",
                online=True,
                connection_type="wired",
                uplink_name="Basement switch",
                signal_dbm=None,
                last_seen="2026-01-01T12:00:00+00:00",
            )
        ]


def create_module():
    return AcmeNetworkModule()
```

`account` contains every field declared by the plugin's own `account_fields`. There is a single
method, `discover_devices()`, which returns every client the controller currently knows about;
it doubles as the connection test (`Admin → Network providers → Test connection` simply calls
it and reports how many devices came back), since a client-list call is the cheapest available
login check a controller offers. Raise `NetworkConnectionError` on any login or API failure
instead of returning an empty list, so TBC can tell "no devices" apart from "could not connect."

`plugin.py` exposes either `create_module()` or a variable named `MODULE`. TBC validates
metadata and `account_fields` from the manifest and transfers them to the module instance.

## Caching and background refresh

TBC never calls `discover_devices()` synchronously while rendering a camera's detail page -
that would block the page on a live controller round-trip for every viewer. Instead, one
background poll cycle (the same loop that refreshes camera status, `poll_interval_seconds`)
refreshes every enabled network account and caches its device list in memory, keyed by
account, since one controller call already covers every camera mapped to that account. The
device-picker on the camera's **Network** tab (used only when an admin is actively choosing
which device to map) is the one place that calls `discover_devices()` on demand, with a
20-second timeout.

## Reference implementation: Ubiquiti UniFi Network

[`TBC-network-ubiquiti`](https://github.com/404GamerNotFound/TBC-network-ubiquiti) signs in to
a self-hosted UniFi Network controller (or a UDM/UDM-Pro's built-in controller) through
[`aiounifi`](https://pypi.org/project/aiounifi/) and reads the active client list
(`Controller.clients`), resolving each client's access point or switch MAC to a friendly name
via `Controller.devices`. `verify_ssl` defaults to off, since almost every local controller
uses a self-signed certificate. This is a network provider only - not to be confused with the
already-existing `unifi_protect` **cloud** plugin, which imports UniFi Protect cameras.

## Reference implementation: AVM FRITZ!Box

[`TBC-fritz.box`](https://github.com/404GamerNotFound/TBC-fritz.box) reads a FRITZ!Box's
device list (`Hosts:GetGenericHostEntry`) and mesh topology (`X_AVM-DE_GetMeshListPath`,
the same data the FRITZ!Box web UI's network map uses) through
[`fritzconnection`](https://pypi.org/project/fritzconnection/), resolving which FRITZ!Box or
mesh repeater each device is currently connected through and, for Wi-Fi clients, signal
quality. `fritzconnection` is synchronous, so every call runs via `asyncio.to_thread()`. The
mesh-topology action isn't available on every Fritz!OS version - `discover_devices()` falls
back to the plain device list (no `uplink_name`) rather than failing outright if it's missing.

## Import, export, and admin interface

Administrators manage network plugins under `Admin → Network providers`, including import,
export, and removal as with camera and cloud plugins. Actual accounts are created at
`/network-accounts`. A plugin assigned to an account cannot be removed, and built-in plugins
cannot be overwritten or removed. `TBC_NETWORK_MODULES_PATH` configures the external storage
location.

Instead of a manual ZIP upload, a network plugin can be installed directly from a public
GitHub repository under `Admin → External sources`. A plugin may include its own `tests/`
directory, which can be started through **Run tests** in the web interface. See
[plugin-sources.md](plugin-sources.md).

## Security

Network account credentials, like cloud and camera credentials, are encrypted at rest. A
network plugin contains executable Python code and has the same privileges as the TBC
process. Import plugins only from trusted sources.
