from ...manual_rtsp.module import ManualRtspCameraModule


class UbiquitiCameraModule(ManualRtspCameraModule):
    def __init__(self) -> None:
        super().__init__(
            manufacturer="Ubiquiti",
            model_hint="UniFi Protect",
            setup_hint="RTSP/RTSPS-Link in UniFi Protect erzeugen und hier vollständig eintragen",
        )
