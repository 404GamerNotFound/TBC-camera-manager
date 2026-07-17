from tbc_camera_api import ManualRtspCameraModule


class RtspOnlyCameraModule(ManualRtspCameraModule):
    def __init__(self) -> None:
        super().__init__(
            manufacturer="RTSP",
            model_hint="Manual stream",
            setup_hint="The manual RTSP/RTSPS address is used without ONVIF",
        )
