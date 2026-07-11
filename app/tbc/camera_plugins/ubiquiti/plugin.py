from tbc_camera_api import import_tbc


def create_module():
    return import_tbc("camera_plugins.ubiquiti.module").UbiquitiCameraModule()
