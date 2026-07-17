"""Loaded via `pytest -p` so a cloud plugin's own tests can import `tbc_cloud_api`.

Plugin code imports `CloudAccountModule`/`CloudDevice`/... from
`tbc_cloud_api`, which TBC's own process only installs into `sys.modules`
when it loads a plugin through `packages.load_plugin_module()`. A plugin's
bundled tests run in a separate pytest subprocess (see plugin_testing.py)
that never goes through that loader, so without this bootstrap
`import tbc_cloud_api` would fail for every externally authored plugin test.
"""

from .packages import _install_plugin_api

_install_plugin_api()
