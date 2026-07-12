from __future__ import annotations

from time import time
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
        from eufy_security import InvalidCredentialsError, async_login
        from eufy_security.errors import NeedVerifyCodeError
    except ImportError as exc:
        raise CloudConnectionError("pyeufysecurity ist nicht installiert") from exc
    email = str(account.get("email") or "").strip()
    password = str(account.get("password") or "")
    country = str(account.get("country") or "DE").strip().upper()
    if not email or not password:
        raise CloudConnectionError("E-Mail-Adresse und Passwort sind erforderlich")
    if len(country) != 2 or not country.isalpha():
        raise CloudConnectionError("Der Ländercode muss aus zwei Buchstaben bestehen")
    verification_code = str(account.get("verification_code") or "").strip()
    login_session = _EufyLoginSession(session, verification_code)
    try:
        api = await async_login(email, password, login_session, country=country)
    except InvalidCredentialsError as exc:
        if verification_code:
            raise CloudConnectionError(
                "Der Eufy-Bestätigungscode ist ungültig oder abgelaufen"
            ) from exc
        raise
    except NeedVerifyCodeError as exc:
        if verification_code:
            raise CloudConnectionError(
                "Der Eufy-Bestätigungscode ist ungültig oder abgelaufen"
            ) from exc
        await _send_verification_code(login_session, country)
        raise CloudConnectionError(
            "Eufy hat einen Bestätigungscode per E-Mail gesendet. Bitte unter "
            "Cloud-Konten → Konto bearbeiten eintragen und erneut verbinden."
        ) from exc
    if verification_code:
        await _trust_device(api, verification_code)
    return api


class _EufyLoginSession:
    """Injects Eufy's 2FA code without modifying the third-party package."""

    def __init__(self, session: Any, verification_code: str) -> None:
        self.raw_session = session
        self.verification_code = verification_code
        self.login_response: dict[str, Any] = {}
        self.api_base = ""

    def __getattr__(self, name: str) -> Any:
        return getattr(self.raw_session, name)

    def post(self, url: str, **kwargs: Any):
        request = self.raw_session.post
        if not url.endswith("/v2/passport/login_sec"):
            return request(url, **kwargs)
        self.api_base = url.removesuffix("/v2/passport/login_sec")
        payload = dict(kwargs.get("json") or {})
        if self.verification_code:
            payload["verify_code"] = self.verification_code
        kwargs["json"] = payload
        return _CapturedLoginRequest(request(url, **kwargs), self)


class _CapturedLoginRequest:
    def __init__(self, request: Any, session: _EufyLoginSession) -> None:
        self.request = request
        self.session = session

    async def __aenter__(self):
        response = await self.request.__aenter__()
        return _CapturedLoginResponse(response, self.session)

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any):
        return await self.request.__aexit__(exc_type, exc, traceback)


class _CapturedLoginResponse:
    def __init__(self, response: Any, session: _EufyLoginSession) -> None:
        self.response = response
        self.session = session

    def __getattr__(self, name: str) -> Any:
        return getattr(self.response, name)

    async def json(self, *args: Any, **kwargs: Any) -> Any:
        data = await self.response.json(*args, **kwargs)
        if isinstance(data, dict):
            self.session.login_response = data
        return data


async def _send_verification_code(session: _EufyLoginSession, country: str) -> None:
    try:
        from eufy_security.api import DEFAULT_HEADERS
    except ImportError as exc:
        raise CloudConnectionError("pyeufysecurity ist nicht installiert") from exc
    auth_data = session.login_response.get("data") or {}
    token = str(auth_data.get("auth_token") or "")
    if not session.api_base or not token:
        raise CloudConnectionError(
            "Eufy verlangt einen Bestätigungscode, konnte ihn aber nicht anfordern"
        )
    headers = {**DEFAULT_HEADERS, "Country": country, "x-auth-token": token}
    async with session.raw_session.post(
        f"{session.api_base}/v1/sms/send/verify_code",
        headers=headers,
        json={"message_type": 2, "transaction": str(int(time() * 1000))},
    ) as response:
        response.raise_for_status()
        result = await response.json(content_type=None)
    if not isinstance(result, dict) or result.get("code") != 0:
        message = result.get("msg") if isinstance(result, dict) else "unbekannter Fehler"
        raise CloudConnectionError(
            f"Eufy-Bestätigungscode konnte nicht angefordert werden: {message}"
        )


async def _trust_device(api: Any, verification_code: str) -> None:
    try:
        await api.request(
            "post",
            "v1/app/trust_device/add",
            json={
                "verify_code": verification_code,
                "transaction": str(int(time() * 1000)),
            },
        )
    except Exception as exc:
        raise CloudConnectionError(
            "Eufy-Anmeldung war erfolgreich, das Gerät konnte aber nicht als vertrauenswürdig gespeichert werden"
        ) from exc


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
        from eufy_security.errors import (
            VerifyCodeError,
            VerifyCodeExpiredError,
            VerifyCodeMaxError,
            VerifyCodeNoneMatchError,
        )
    except ImportError:
        return f"Eufy-Verbindung fehlgeschlagen: {exc}"
    if isinstance(exc, InvalidCredentialsError):
        return "Eufy-Anmeldung fehlgeschlagen: E-Mail-Adresse oder Passwort falsch"
    if isinstance(
        exc,
        (
            VerifyCodeError,
            VerifyCodeExpiredError,
            VerifyCodeMaxError,
            VerifyCodeNoneMatchError,
        ),
    ):
        return "Der Eufy-Bestätigungscode ist ungültig oder abgelaufen"
    if isinstance(exc, CaptchaRequiredError):
        return (
            "Eufy verlangt eine CAPTCHA-Prüfung. Bitte das Konto einmal in der "
            "Eufy-App bestätigen und danach erneut testen."
        )
    return f"Eufy-Verbindung fehlgeschlagen: {exc}"


def create_module():
    return EufyCloudModule()
