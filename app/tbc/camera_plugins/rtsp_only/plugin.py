from tbc_camera_api import import_tbc


def create_module():
    return import_tbc("rtsp_only.module").RtspOnlyCameraModule()
