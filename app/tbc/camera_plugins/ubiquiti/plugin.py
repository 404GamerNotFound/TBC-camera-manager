from tbc_camera_api import import_tbc


def create_module():
    return import_tbc("ubiquiti.module").UbiquitiCameraModule()
