from __future__ import annotations

from typing import Any
from urllib.parse import quote

from tbc_cloud_api import CloudAccountModule, CloudConnectionError, CloudDevice


class EufyCloudModule(CloudAccountModule):
    """Discovers cameras through Eufy's private cloud API.

    Only stable local RTSP URLs are handed to TBC. Starting a cloud stream
    during discovery would return a short-lived session URL and would leave a
    vendor-side stream running, so cameras without local RTSP remain visible
    but cannot be imported as regular cameras.
    """

    async def test_connection(self, account: dict[str, Any]) -> str:
        try:
            async with _client_session() as session:
                api = await _login(account, session)
                camera_count = len(api.cameras)
                station_count = len(api.stations)
        except Exception as exc:
            raise CloudConnectionError(_error_message(exc)) from exc
        return f"Mit Eufy Security verbunden ({camera_count} Kamera(s), {station_count} Station(en))"

    async def discover_devices(self, account: dict[str, Any]) -> list[CloudDevice]:
        try:
            async with _client_session() as session:
                api = await _login(account, session)
                return [_device(camera, account) for camera in api.cameras.values()]
        except Exception as exc:
            raise CloudConnectionError(_error_message(exc)) from exc


def _client_session():
    try:
        from aiohttp import ClientSession
    except ImportError as exc:
        raise CloudConnectionError("aiohttp ist nicht installiert") from exc
    return ClientSession()


async def _login(account: dict[str, Any], session: Any) -> Any:
    try:
        from eufy_security import async_login
    except ImportError as exc:
        raise CloudConnectionError("pyeufysecurity ist nicht installiert") from exc
    email = str(account.get("email") or "").strip()
    password = str(account.get("password") or "")
    country = str(account.get("country") or "DE").strip().upper()
    if not email or not password:
        raise CloudConnectionError("E-Mail-Adresse und Passwort sind erforderlich")
    if len(country) != 2 or not country.isalpha():
        raise CloudConnectionError("Der Ländercode muss aus zwei Buchstaben bestehen")
    return await async_login(email, password, session, country=country)


def _device(camera: Any, account: dict[str, Any]) -> CloudDevice:
    ip_address = str(getattr(camera, "ip_address", None) or "").strip()
    rtsp_username = str(account.get("rtsp_username") or "")
    rtsp_password = str(account.get("rtsp_password") or "")
    stream_uri = None
    if ip_address and rtsp_username and rtsp_password:
        username = quote(rtsp_username, safe="")
        password = quote(rtsp_password, safe="")
        stream_uri = f"rtsp://{username}:{password}@{ip_address}:554/live0"
    return CloudDevice(
        external_id=str(camera.serial),
        name=str(camera.name or camera.serial),
        model=str(camera.model or "") or None,
        online=None,
        manual_stream_uri=stream_uri,
        suggested_module_key="rtsp_only",
    )


def _error_message(exc: Exception) -> str:
    if isinstance(exc, CloudConnectionError):
        return str(exc)
    try:
        from eufy_security import CaptchaRequiredError, InvalidCredentialsError
    except ImportError:
        return f"Eufy-Verbindung fehlgeschlagen: {exc}"
    if isinstance(exc, InvalidCredentialsError):
        return "Eufy-Anmeldung fehlgeschlagen: E-Mail-Adresse oder Passwort falsch"
    if isinstance(exc, CaptchaRequiredError):
        return (
            "Eufy verlangt eine CAPTCHA-Prüfung. Bitte das Konto einmal in der "
            "Eufy-App bestätigen und danach erneut testen."
        )
    return f"Eufy-Verbindung fehlgeschlagen: {exc}"


def create_module():
    return EufyCloudModule()
