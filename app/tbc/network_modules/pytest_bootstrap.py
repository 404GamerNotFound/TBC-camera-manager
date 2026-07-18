"""Loaded via `pytest -p` so a network plugin's own tests can import `tbc_network_api`.

Plugin code imports `NetworkAccountModule`/`NetworkDevice`/... from
`tbc_network_api`, which TBC's own process only installs into `sys.modules`
when it loads a plugin through `packages.load_plugin_module()`. A plugin's
bundled tests run in a separate pytest subprocess (see plugin_testing.py)
that never goes through that loader, so without this bootstrap
`import tbc_network_api` would fail for every externally authored plugin test.
"""

from .packages import _install_plugin_api

_install_plugin_api()
