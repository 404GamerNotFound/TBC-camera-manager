# Developing cloud accounts

TBC separates camera protocols, described in [camera-modules.md](camera-modules.md), from cloud
accounts. A camera module communicates directly with one camera through a host, port, and
credentials. A cloud account signs in to one manufacturer account and lists multiple devices.
The two layers are therefore implemented as separate plugin systems.

After a cloud account discovers devices, TBC creates standard entries for them in the
`cameras` table. They use the same live-view, control, and detection infrastructure as every
other camera. A cloud plugin does not need its own `CameraModule` when its account API can
resolve a device to a persistent RTSP or RTSPS URL.

## Plugin file and account form

A cloud-plugin ZIP follows the same layout as a camera-plugin ZIP: files reside directly at
the archive root or inside exactly one common directory, with `manifest.json` as the
authoritative configuration:

```json
{
  "schema_version": 1,
  "key": "acme_cloud",
  "label": "Acme Cloud",
  "version": "1.0.0",
  "description": "Acme camera accounts",
  "entrypoint": "plugin.py",
  "auth_type": "credentials",
  "verification_support": "not_applicable",
  "requirements": ["acme-cloud-sdk==1.0.0"],
  "account_fields": [
    {
      "key": "email",
      "label": "Email address",
      "type": "email",
      "required": true,
      "autocomplete": "username"
    },
    {
      "key": "password",
      "label": "Password",
      "type": "password",
      "required": true,
      "autocomplete": "current-password"
    },
    {
      "key": "region",
      "label": "Region",
      "type": "select",
      "default": "eu",
      "options": [
        {"value": "eu", "label": "Europe"},
        {"value": "us", "label": "United States"}
      ]
    }
  ]
}
```

`requirements` is optional - a list of the plugin's own pip dependencies TBC does not already
ship, installed on demand with an explicit admin confirmation instead of having to live in
TBC's own `requirements.txt`. See
[**Plugin-declared pip requirements**](plugin-sources.md#plugin-declared-pip-requirements-requirements)
in plugin-sources.md.

`account_fields` is the complete, plugin-supplied description of the account form. The main
project has no knowledge of provider-specific fields. Supported types are `text`, `email`,
`password`, `number`, `checkbox`, and `select`. Every field may define `required`,
`placeholder`, `help_text`, `autocomplete`, `default`, `min`, `max`, `full_width`, and
`transient`; select fields may also define `options`. After a successful connection attempt or
one explicitly rejected by the plugin, TBC automatically clears a field with
`transient: true`. This is intended for one-time codes. Keys may contain lowercase letters,
numbers, and underscores.

Transient fields intentionally do not appear in the **Add account** or **Edit account** form.
When an account is first created, the administrator has not yet received a code, so showing an
empty code field would be confusing. TBC asks for these fields only on the verification page
described under **Two-factor and verification codes**, which appears after an actual
`CloudVerificationRequired` exception.

`verification_support` is the plugin's authoritative declaration of whether its provider may
request a verification code. Use `supported` when the plugin raises
`CloudVerificationRequired` as described below, otherwise use `not_applicable`. If the field is
absent from the manifest, `not_applicable` is the honest default. It does not claim that the
provider needs no 2FA; it means only that the plugin reports no support. The admin interface
shows this value as a badge for every installed cloud provider under
`Admin → Cloud providers`, making accounts that may require a second step easy to identify.

On submission, TBC validates only the selected plugin's fields and stores them as JSON in
`cloud_accounts.config_json`. Before calling `test_connection()` or `discover_devices()`, TBC
also flattens the configuration into the `account` dictionary so a plugin can read
`account["email"]` directly. Legacy schema-v1 values `identifier_label`, `secret_label`,
`requires_host`, and `default_port` remain compatible. If `account_fields` is absent, the
loader generates the original standard form from those values.

Every cloud plugin - including the reference ones below - is a self-contained external plugin,
installed like any other from `STANDARD_PLUGIN_SOURCES` or a custom GitHub repository. TBC
ships none of them built-in; see [plugin-sources.md](plugin-sources.md).

## Public contract

A cloud plugin inherits from `tbc_cloud_api.CloudAccountModule`:

```python
from tbc_cloud_api import CloudAccountModule, CloudDevice


class AcmeCloudModule(CloudAccountModule):
    async def test_connection(self, account: dict) -> str:
        return "Connected to Acme account"

    async def discover_devices(self, account: dict) -> list[CloudDevice]:
        return [
            CloudDevice(
                external_id="cam-1",
                name="Entrance",
                manual_stream_uri="rtsp://192.0.2.10:554/stream1",
                suggested_module_key="rtsp_only",
            )
        ]


def create_module():
    return AcmeCloudModule()
```

`account` contains generic account metadata and every field declared by the plugin. Modules
raise `CloudConnectionError` on failure. `CloudDevice.manual_stream_uri` is optional. When the
API provides no persistent stream URL, leave it empty; the web interface then omits the
**Add as camera** button for that device.

`plugin.py` exposes either `create_module()` or a variable named `MODULE`. TBC validates
metadata and `account_fields` from the manifest and transfers them to the module instance.

### Two-factor and verification codes

When a manufacturer requires a code before completing sign-in, whether through email, SMS,
or app confirmation, `test_connection()` or `discover_devices()` raises
`CloudVerificationRequired` instead of a regular `CloudConnectionError`:

```python
from tbc_cloud_api import CloudVerificationRequired

raise CloudVerificationRequired(
    "Acme sent a verification code by email.",
    field_key="verification_code",
)
```

`field_key` must be the key of an entry in the plugin's own `account_fields`, usually with
`transient: true`. The web interface catches this exception centrally, stores the field and
message on the account as `pending_verification_field` and `pending_verification_message`, and
redirects the administrator to `/cloud-accounts/{id}/verify` instead of displaying an error.
This plugin-neutral verification page contains exactly one input for the code. After
submission, TBC calls `test_connection()` again automatically. If the plugin raises
`CloudVerificationRequired` again, the administrator remains on the verification page. For
any other error, TBC returns to the account list, and a new connection attempt requests a new
code. Editing the account through **Edit account** discards pending verification because the
corresponding login request could otherwise no longer be identified reliably.

A plugin that must preserve state between requesting and entering a code, for example to
continue the same partial login instead of starting again, manages that state itself. A common
implementation is a process-wide, time-limited cache such as `_PENDING_CHALLENGES` in the
[`TBC-eufy`](https://github.com/404GamerNotFound/TBC-eufy) plugin. TBC passes only the
administrator-entered code as a field value.

## Reference implementation: UniFi Protect

[`TBC-unifi-protect`](https://github.com/404GamerNotFound/TBC-unifi-protect) signs in to a
controller through [`uiprotect`](https://pypi.org/project/uiprotect/), either locally by IP
address or through a `<console-id>.ui.com` cloud address. `discover_devices()` reads
`ProtectApiClient.update()` → `Bootstrap.cameras` and resolves the first RTSP-enabled channel
through `CameraChannel.rtsp_url`. When RTSP is disabled, `manual_stream_uri` remains empty.
Discovered devices use `suggested_module_key="ubiquiti"`.

`uiprotect` currently provides no API for two-factor or verification codes: it exposes neither
a suitable exception nor a login method for them. The plugin therefore honestly declares
`verification_support: "not_applicable"` instead of claiming support it cannot provide. When
authentication fails with `NotAuthorized`, the error also explains that account-level 2FA
might be the cause without presenting that as certain, because the library cannot determine
it reliably. Affected administrators need a separate local account without 2FA.

## Reference implementation: Eufy Security

[`TBC-eufy`](https://github.com/404GamerNotFound/TBC-eufy) uses
[`pyeufysecurity`](https://pypi.org/project/pyeufysecurity/) for encrypted Eufy v2 cloud
authentication and device discovery. Its manifest supplies an email address, password, ISO
country code, one-time verification code with `transient: true`, and optional local RTSP
credentials. A separate guest account shared through the Eufy app is recommended.

When Eufy requires confirmation for a new client, the plugin requests a code through Eufy's
email endpoint and raises `CloudVerificationRequired(field_key="verification_code")`. The web
interface then redirects to the account verification page. The associated challenge remains
in process memory for ten minutes so the second login can reuse the same temporary token and
ECDH key. After the code is entered, the client is registered as trusted, the challenge is
removed, and the stored one-time code is cleared automatically. An old code without a matching
challenge is discarded. An invalid or expired code returns to the account list and requires a
new **Test connection** attempt to request a fresh code, just as after a container restart
clears process memory. If Eufy requires a CAPTCHA instead, it must still be confirmed in the
Eufy app.

The Eufy cloud returns only a session-bound URL for a started stream. `discover_devices()`
therefore starts no cloud streams and stores no short-lived URLs. If a camera has a local IP
address and RTSP credentials are configured, the plugin constructs the persistent local
`rtsp://…/live0` address and sets `suggested_module_key="rtsp_only"`. For every other Eufy
camera, `manual_stream_uri` remains empty. Such devices appear in discovery but can be added as
cameras only after NAS or RTSP has been enabled in the Eufy app.

Every Eufy connection test and device-discovery request generates a short debug ID. Error
messages display this ID, while the admin debug log records the API step, HTTP status, original
content type, Eufy error code, sanitized Eufy message, and response data type. Credentials,
authentication tokens, verification codes, encrypted payloads, and complete API responses are
never logged.

## Reference implementation: eWeLink (SONOFF)

[`TBC-ewelink`](https://github.com/404GamerNotFound/TBC-ewelink) uses the
[`ewelink`](https://pypi.org/project/ewelink/) library, which calls the official CoolKit Open
Platform API through `v2/user/login`,
`v2/device/thing`, and HMAC-signed requests. Unlike Eufy or UniFi Protect, an eWeLink app
account with email and password is not sufficient. CoolKit also requires a dedicated **app ID
and app secret**, which can be registered for free at
[dev.ewelink.cc](https://dev.ewelink.cc/). This deliberately avoids reverse-engineered app
credentials circulated by community projects, which CoolKit could revoke at any time. The
manifest requests both values in addition to the email address and password.

The official API reports region failures itself; error code `10004` returns the responsible
region, so the plugin does not need to configure or guess it. The library provides no API for
two-factor codes, so `verification_support` is `not_applicable`.

`discover_devices()` lists every account device with its name, model, and online status, but
returns **no** RTSP URL. The official eWeLink cloud API exposes neither a local IP address nor
a stream link. SONOFF cameras still generate their RTSP link exclusively in the eWeLink app:
open the camera, enable RTSP, and copy the link. Enter that link manually in the installed
`sonoff` camera module. Device discovery therefore provides inventory only, not automatic
camera import. Unlike UniFi Protect and, in part, Eufy, TBC does not display **Add as camera**
for eWeLink devices.

## Reference implementation: Google Nest

[`TBC-google`](https://github.com/404GamerNotFound/TBC-google) talks directly to Google's
official [Smart Device Management (SDM) API](https://developers.google.com/nest/device-access)
with `aiohttp` - no vendor SDK exists for it. The manifest requests a Device Access **Project
ID**, an OAuth **client ID/secret**, and a **refresh token**; obtaining all three is a one-time,
outside-of-TBC setup (Device Access Console registration, an OAuth client in Google Cloud
Console, and a manual authorization-code exchange) documented in the plugin's own README, since
none of it fits a login form. Once obtained, the refresh token is a static, long-lived secret
like an API key - `test_connection()`/`discover_devices()` exchange it for a short-lived access
token on every call, the same as any other credential-based cloud plugin here.

`discover_devices()` lists every device under the project and keeps only the ones carrying a
camera- or doorbell-related trait (`CameraLiveStream`, `CameraImage`, `CameraEventImage`, or
`DoorbellChime`) rather than trusting the device `type` string, since Google's own docs warn
against inferring capability from `type` alone. Like eWeLink and X-Sense, it returns **no**
`manual_stream_uri`: the SDM API's `CameraLiveStream` trait only ever produces a stream valid for
about 5 minutes, and devices already migrated to the Google Home app support WebRTC only, not
RTSP - neither fits a manual RTSP URL a camera module could reopen later. Discovery therefore
provides inventory only; TBC does not display **Add as camera** for Google Nest devices.

The refresh token itself has no documented in-app two-factor flow to hook into, so
`verification_support` is `not_applicable`. Google requires the refresh token to be used at
least once every 6 months or it stops working, which TBC's periodic connection checks satisfy on
their own as long as the account stays configured.

## Reference implementation: X-Sense

[`TBC-X-Sense`](https://github.com/404GamerNotFound/TBC-X-Sense) is a *cloud* plugin (its
`cloud/` subdirectory - the repo also ships a matching `camera/` plugin, see
[camera-modules.md](camera-modules.md)) for X-Sense's account API. Unlike every other cloud
plugin here, X-Sense has no official developer API at all - the entire integration is
reverse-engineered, including a fixed device-identity block that mimics X-Sense's own Android
app. `discover_devices()` lists cameras (model, serial, name) for inventory only and, like
eWeLink, never returns a stream URL: X-Sense's live-view endpoint issues a short-lived session
ticket rather than a persistent address, so there is nothing stable to hand back from a
one-time discovery call. Instead, admins add the camera manually with the matching `camera/`
plugin, whose `probe()` re-fetches a fresh live-view URL on every background poll cycle - see
that plugin's README for why. `verification_support` is `not_applicable`; the reverse-engineered
API this depends on has no documented two-factor flow to hook into.

## Import, export, and admin interface

Administrators manage cloud plugins under `Admin → Cloud providers`, including import,
export, and removal as with camera plugins. Actual accounts are created outside the admin
area through `Add camera → Cloud account` at `/cloud-accounts`, because connecting a cloud
account is part of camera setup rather than purely an administration task. From there,
administrators create an account, edit plugin fields, test the connection, and discover
devices.

When a plugin requests a verification code, the account card replaces **Test connection**
with **Enter verification code** and opens the plugin-neutral page containing one input,
regardless of which plugin requested the code. A plugin assigned to an account cannot be
removed, and built-in plugins cannot be overwritten or removed. `TBC_CLOUD_MODULES_PATH`
configures the external storage location.

Instead of a manual ZIP upload, a cloud plugin can be installed directly from a public GitHub
repository under `Admin → External sources`. A plugin may include its own `tests/` directory,
which can be started through **Run tests** in the web interface. See
[plugin-sources.md](plugin-sources.md).

## Security

Cloud credentials, like camera credentials, are stored unencrypted in the TBC database. A
cloud plugin contains executable Python code and has the same privileges as the TBC process.
Import plugins only from trusted sources.
