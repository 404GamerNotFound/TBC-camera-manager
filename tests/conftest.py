"""Session-wide pytest bootstrap.

Built-in camera plugins (app/tbc/camera_plugins/<key>/) resolve shared,
manufacturer-neutral helpers (ONVIF probing, stream URIs, detection
definitions, the CameraModule base classes, ...) through the `tbc_camera_api`
facade module instead of relative imports into the main app package - the
same mechanism externally installed plugins use. That facade is normally
registered in sys.modules as a side effect of loading a plugin through the
registry (`camera_modules.packages.load_plugin_module`). Tests that import a
plugin's implementation module directly (e.g. `from
app.tbc.camera_plugins.reolink import service`) bypass that loading path, so
the facade needs to be installed once up front here.
"""

from app.tbc.camera_modules.packages import _install_plugin_api

_install_plugin_api()
