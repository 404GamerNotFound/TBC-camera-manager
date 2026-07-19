# Plugin tests and external sources

This page extends [camera-modules.md](camera-modules.md) for camera plugins,
[cloud-accounts.md](cloud-accounts.md) for cloud plugins,
[network-accounts.md](network-accounts.md) for network providers, and
[design-themes.md](design-themes.md) for themes with capabilities shared by all four plugin
types: plugins can include their own tests, plugins can be installed directly from a public
GitHub repository instead of through a manual ZIP upload, and camera/cloud/network plugins can
declare their own Python package requirements instead of needing them baked into TBC itself.

## Tests inside a plugin (`tests/`)

A camera, cloud, or network plugin may include a `tests/` directory with pytest tests
(`test_*.py`) next to `manifest.json` and its entry point. This does not require a separate
feature flag: ZIP validation already accepts `.py` files anywhere inside the plugin directory,
so a `tests/` subdirectory is automatically allowed. Exporting a plugin from
`Admin → Camera plugins`, `Admin → Cloud providers`, or `Admin → Network providers` includes
the complete plugin directory, including `tests/`. An exported built-in plugin is therefore
just as self-contained and testable as an externally installed plugin.

Theme packages intentionally contain no executable code and therefore no tests; see
[design-themes.md](design-themes.md).

The reference example is
[`TBC-unifi-protect/tests/test_module.py`](https://github.com/404GamerNotFound/TBC-unifi-protect),
an external plugin whose tests live entirely inside its own repository rather than the
project-wide `tests/` directory. Some older built-in plugins still keep tests in the
project-wide directory. That layout remains valid, but new and externally contributed plugins
should use the in-plugin convention.

### Running tests

For every plugin that contains a `tests/` directory, `Admin → Camera plugins`,
`Admin → Cloud providers`, and `Admin → Network providers` display a **Run tests** button. It starts
`pytest <plugin>/tests/ -q` as a subprocess with a 120-second timeout and reports success or
failure in the interface. The complete output is written to the admin debug log. Running tests
does not create a new trust boundary: plugin code already runs with the same privileges as the
TBC process when it is imported. As explained under **Security** in camera-modules.md and
cloud-accounts.md, the test run executes the same already trusted code explicitly rather than
implicitly.

## External sources (`Admin → External sources`)

Instead of manually uploading a ZIP, a plugin can be installed directly from a public GitHub
repository. Register a source under `Admin → External sources` with these values:

- **Plugin type**: camera plugin, cloud provider, network provider, or theme.
- **Repository URL**: `https://github.com/<owner>/<repository>`. Only public GitHub
  repositories are supported; no token or other hosts are supported.
- **Branch/tag**: defaults to `main`.
- **Subdirectory** (optional): path to the directory containing `manifest.json` when the
  plugin is not located at the repository root, for example in a multi-plugin repository or
  as part of a larger project.

**Synchronize** first resolves the configured branch or tag to a specific commit SHA through
the GitHub API `commits` endpoint. It downloads the repository archive for exactly that SHA
through the official unauthenticated `zipball` endpoint
(`https://api.github.com/repos/<owner>/<repository>/zipball/<sha>`), extracts only the
configured subdirectory when necessary, and passes the result to the same installation path
used by a manual ZIP upload (`app/tbc/plugin_sources.py`, function
`resolve_and_fetch_plugin`). The same security checks therefore apply: path-traversal
protection, allowed file types, size limits, and protection against overwriting built-in
plugins. The installed SHA is stored as `installed_ref_sha` and is used for update detection.

Git-specific metadata such as `.gitattributes`, `.gitignore`, `.gitmodules`, `.github/`,
`.editorconfig`, and `.dockerignore` may exist in the repository. These entries are omitted
while preparing the GitHub archive because they are not part of the executable plugin
package. The same applies to local development artifacts such as `__pycache__/`,
`.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.DS_Store`, `*.pyc`, and `*.pyo`. Such
files should also be excluded by the plugin repository's `.gitignore`. All other files still
pass through the plugin installer's file-type and path validation unchanged.

Removing a source with **Remove source** deletes only its registration, not the installed
plugin. Remove the installed plugin separately through its plugin-management page, where the
protections against removing built-in or currently used plugins still apply.

### Default repositories

TBC can offer commonly used public plugins as preconfigured default repositories. They appear
above manual source management and are registered and installed only after an administrator
explicitly selects them. All of them use the `main` branch, listed here by plugin type:

**Camera plugins:**

- [Aqara](https://github.com/404GamerNotFound/TBC-aqara)
- [Axis](https://github.com/404GamerNotFound/TBC-axis)
- [Dahua](https://github.com/404GamerNotFound/TBC-dahua)
- [Foscam](https://github.com/404GamerNotFound/TBC-foscam)
- [Hikvision](https://github.com/404GamerNotFound/TBC-hikvision)
- [Reolink](https://github.com/404GamerNotFound/TBC-reolink)
- [SONOFF](https://github.com/404GamerNotFound/TBC-sonoff)
- [TP-Link/Tapo](https://github.com/404GamerNotFound/TBC-tplink)
- [Ubiquiti/UniFi Protect (manual RTSP link)](https://github.com/404GamerNotFound/TBC-ubiquiti)
- [X-Sense (`camera/` subdirectory)](https://github.com/404GamerNotFound/TBC-X-Sense)

**Network providers:**

- [Ubiquiti UniFi Network](https://github.com/404GamerNotFound/TBC-network-ubiquiti)
- [AVM FRITZ!Box](https://github.com/404GamerNotFound/TBC-fritz.box)

**Cloud providers:**

- [Eufy Security](https://github.com/404GamerNotFound/TBC-eufy)
- [UniFi Protect (controller account)](https://github.com/404GamerNotFound/TBC-unifi-protect)
- [eWeLink (SONOFF)](https://github.com/404GamerNotFound/TBC-ewelink)
- [X-Sense (`cloud/` subdirectory)](https://github.com/404GamerNotFound/TBC-X-Sense)

The two Ubiquiti and two X-Sense entries are intentionally separate: "Ubiquiti/UniFi Protect"
under camera plugins is TBC's own manual-RTSP-link module, while "UniFi Protect" under cloud
providers signs in to the controller itself and discovers cameras automatically (see
[cloud-accounts.md](cloud-accounts.md)). X-Sense ships one repository with a `camera/` and a
`cloud/` subdirectory, registered here as two separate sources via the `subdirectory` field.

Direct installation does not use a separate or less strict installation path. After the
one-time registration, TBC performs the same GitHub resolution, archive preparation, and
package validation as for a manually created external source. If the same repository is
already registered as a camera source, even with an optional `.git` suffix, different letter
case, or a trailing slash, TBC synchronizes the existing registration rather than creating a
duplicate. A failed initial installation leaves the registration in an error state so the
administrator can retry with **Synchronize**.

### Required structure

A plugin installed from an external source must have the same structure as a manually
uploaded ZIP: `manifest.json` in the configured directory, the entry point named by the
manifest, and optionally a `tests/` directory for camera, cloud, and network plugins. Tests are not an
installation requirement. A plugin without `tests/` is accepted like one with tests, but no
**Run tests** button appears in the plugin overview. New externally contributed plugins
should nevertheless include tests so an administrator can validate unfamiliar code against
its own test suite before production use.

`Admin → External sources` also explains this structure in the web interface and provides a
downloadable, fully installable template for every plugin type: **Template: Camera plugin**,
**Cloud provider**, **Network provider**, or **Theme**, generated by
`app/tbc/plugin_templates.py`. Each template contains a manifest and entry point; camera,
cloud, and network templates also contain a `tests/` directory with a runnable example test.
TBC's own test suite installs every template and runs its tests before release, so these are
functional starting points for renaming and extension, not merely text examples.

### Automatic update detection (`Admin → Updates`)

TBC checks every registered source automatically once per hour. The background task performs
its first check 30 seconds after startup and repeats every 60 minutes. It requests only the
current commit SHA of the branch or tag with
`GET /repos/<owner>/<repository>/commits/<ref>` and
`Accept: application/vnd.github.sha`, which returns one 40-character value without downloading
the repository, then compares it with the last installed SHA. When they differ, the source
appears under `Admin → Updates`, and the menu displays the number of pending updates, for
example **Updates (2)**. **Update now** performs the same synchronization as the source page.
If an update fails, it remains pending until an attempt succeeds. TBC never installs these
updates automatically: the hourly check changes only the displayed status, and every actual
installation still requires an explicit click.

## Plugin-declared pip requirements (`requirements`)

Camera, cloud, and network plugins may need a third-party Python package TBC itself does not
ship, for example `reolink-aio` for advanced Reolink features or `fritzconnection` for
FRITZ!Box. Rather than hard-coding every plugin's dependency into TBC's own `requirements.txt`
- which would force a main-repository change and a full rebuild for every new plugin, defeating
the point of plugins being independently installable - a plugin declares its own pip
requirements in its manifest:

```json
{
  "schema_version": 1,
  "key": "acme_camera",
  "entrypoint": "plugin.py",
  "requirements": ["acme-camera-sdk==2.1.0", "aiohttp>=3.9,<4"]
}
```

`requirements` is an optional list of up to 20 pip specifier strings - anything `pip install`
itself accepts, such as `package==1.2.3` or `package>=1.0,<2`. Design themes ship no Python and
therefore have no `requirements` field. Declare every package the plugin's own code actually
imports, including one already guaranteed by TBC (`aiohttp`, `boto3`, `packaging`, ...) - that
declaration is redundant today, but keeps the manifest accurate and the plugin correctly
self-describing if that guarantee ever changes.

### Enforcement and the confirmation step

TBC checks a plugin's declared requirements against the packages actually installed in its own
Python environment (via `importlib.metadata`, matched by pip/PyPI distribution name - not
necessarily the name used in `import`, which can differ) at the same point for every
installation path: manual ZIP upload, GitHub sync, and one-click **Install directly** from a
default repository, right before the plugin's code is imported for the first time. If a
requirement is missing, or an installed version does not satisfy the specifier, installation is
blocked and the administrator is redirected to a confirmation page instead of the plugin
silently failing to load with an opaque `ModuleNotFoundError` later.

The confirmation page lists exactly which packages are missing and requires an explicit
**Install now** click before anything happens - TBC never runs `pip install` on its own or as a
side effect of the hourly update check above. Once confirmed, TBC installs the listed packages
into the running container (`pip install --user <packages>`, or a plain install when already
running inside a virtualenv) and automatically retries the installation or synchronization that
triggered the check, so a GitHub-sourced plugin never needs a second manual click. A ZIP upload
has no archive left to retry automatically; re-upload the same file once the packages are
installed. Installation happens into the already-running process - no container restart is
needed before the plugin loads successfully.

For a camera plugin, any already-configured camera on that module is automatically refreshed
right after a successful install, so its detail page immediately reflects the newly available
functionality instead of showing a stale probe result (e.g. an ONVIF-only fallback message)
until the next background poll cycle or a manual **Refresh** click.

## Security

A plugin installed from an external source contains the same executable code as a manually
uploaded ZIP and runs in exactly the same way. The warnings in camera-modules.md and
cloud-accounts.md still apply: register only trusted repositories. Registering a source alone
does not download or install anything. Code changes only after an administrator explicitly
selects **Synchronize**. The hourly update check downloads no code, requests only one commit
SHA, executes nothing new, and installs nothing automatically.

**Run tests**, when supplied by a plugin, starts a separate Python process with the same
privileges as the TBC process. As explained under **Tests inside a plugin**, this is
intentionally not a sandbox. A malicious plugin could theoretically cause damage through its
tests as well. The protection is to register only trusted sources.

Installing a plugin's declared `requirements` runs `pip install` with the same privileges as
the TBC process, fetching from PyPI - also not sandboxed. TBC never runs it without an explicit
administrator confirmation and never as a side effect of any automatic check; review a
plugin's declared `requirements` the same way you would review its code before confirming.
