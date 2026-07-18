"""Container package for built-in network-account plugins.

Mirrors cloud_plugins/__init__.py: every built-in plugin resolves the
NetworkAccountModule contract through the `tbc_network_api` facade instead of
relative imports into the main app package, the same mechanism externally
installed (ZIP-uploaded) network plugins use. Installing the facade here
guarantees it exists before any submodule is imported, regardless of import
path. See docs/network-accounts.md.

No plugins ship built in here today - unlike ONVIF for cameras, there is no
vendor-neutral network-controller protocol to fall back to, so this package
exists purely for structural symmetry and as a home for a future generic
plugin (mirrors cloud_plugins/, which ships zero generic fallbacks either).
"""

from ..network_modules.packages import _install_plugin_api

_install_plugin_api()
