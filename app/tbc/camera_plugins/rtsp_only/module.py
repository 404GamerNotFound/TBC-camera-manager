from ...manual_rtsp.module import ManualRtspCameraModule


class RtspOnlyCameraModule(ManualRtspCameraModule):
    def __init__(self) -> None:
        super().__init__(
            manufacturer="RTSP",
            model_hint="Manueller Stream",
            setup_hint="Die manuelle RTSP-/RTSPS-Adresse wird ohne ONVIF verwendet",
        )
