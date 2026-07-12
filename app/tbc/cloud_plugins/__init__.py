"""Container package for built-in cloud-account plugins.

Mirrors camera_plugins/__init__.py: every built-in plugin resolves the
CloudAccountModule contract through the `tbc_cloud_api` facade instead of
relative imports into the main app package, the same mechanism externally
installed (ZIP-uploaded) cloud plugins use. Installing the facade here
guarantees it exists before any submodule is imported, regardless of import
path. See docs/cloud-accounts.md.
"""

from ..cloud_modules.packages import _install_plugin_api

_install_plugin_api()
