"""Container package for built-in camera plugins.

Every built-in plugin's device-specific code (module.py, service.py,
catalog.py, control.py, ...) lives under a subpackage here and resolves
shared, manufacturer-neutral platform helpers through the `tbc_camera_api`
facade instead of relative imports into the main app package - the same
mechanism externally installed (ZIP-uploaded) plugins use. See
docs/camera-modules.md.

That facade must exist in sys.modules before any such file is imported.
Python always imports a package's __init__.py before any of its submodules,
so installing it here - rather than relying on callers to install it first,
or on it having been installed as a side effect of an unrelated earlier
import - guarantees it is in place for every possible built-in plugin import.
"""

from ..camera_modules.packages import _install_plugin_api

_install_plugin_api()
