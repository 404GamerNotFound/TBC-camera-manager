from ..manual_rtsp.module import ManualRtspCameraModule


class SonoffCameraModule(ManualRtspCameraModule):
    def __init__(self) -> None:
        super().__init__(
            manufacturer="SONOFF",
            model_hint="SONOFF Kamera",
            setup_hint="RTSP in eWeLink aktivieren, Link erzeugen und hier vollständig eintragen",
        )
