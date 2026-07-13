from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from hashlib import sha256
from secrets import token_hex
from threading import Lock
from time import monotonic, time
from typing import Any
from urllib.parse import quote

from tbc_cloud_api import CloudAccountModule, CloudConnectionError, CloudDevice, CloudVerificationRequired


LOGGER = logging.getLogger("tbc.cloud.eufy")
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w.-]+")
CHALLENGE_TTL_SECONDS = 10 * 60


@dataclass
class _PendingChallenge:
    api: Any
    temporary_token: str
    expires_at: float


_PENDING_CHALLENGES: dict[str, _PendingChallenge] = {}
_PENDING_CHALLENGES_LOCK = Lock()


class EufyCloudModule(CloudAccountModule):
    """Discovers cameras through Eufy's private cloud API.

    Only stable local RTSP URLs are handed to TBC. Starting a cloud stream
    during discovery would return a short-lived session URL and would leave a
    vendor-side stream running, so cameras without local RTSP remain visible
    but cannot be imported as regular cameras.
    """

    async def test_connection(self, account: dict[str, Any]) -> str:
        debug_id = token_hex(4)
        LOGGER.debug(
            "Eufy-Verbindungstest gestartet | debug_id=%s country=%s verification_code=%s",
            debug_id,
            str(account.get("country") or "DE").upper(),
            bool(account.get("verification_code")),
        )
        try:
            async with _client_session() as session:
                api = await _login(account, session, debug_id)
                camera_count = len(api.cameras)
                station_count = len(api.stations)
        except CloudVerificationRequired:
            # Not a failure: propagate unchanged so the web layer can route to
            # the dedicated confirmation page instead of showing a plain error.
            raise
        except Exception as exc:
            LOGGER.exception(
                "Eufy-Verbindungstest fehlgeschlagen | debug_id=%s error_type=%s",
                debug_id,
                type(exc).__name__,
            )
            raise CloudConnectionError(f"{_error_message(exc)} (Debug-ID: {debug_id})") from exc
        LOGGER.info(
            "Eufy-Verbindungstest erfolgreich | debug_id=%s cameras=%s stations=%s",
            debug_id,
            camera_count,
            station_count,
        )
        return f"Mit Eufy Security verbunden ({camera_count} Kamera(s), {station_count} Station(en))"

    async def discover_devices(self, account: dict[str, Any]) -> list[CloudDevice]:
        debug_id = token_hex(4)
        LOGGER.debug(
            "Eufy-Gerätesuche gestartet | debug_id=%s country=%s verification_code=%s",
            debug_id,
            str(account.get("country") or "DE").upper(),
            bool(account.get("verification_code")),
        )
        try:
            async with _client_session() as session:
                api = await _login(account, session, debug_id)
                devices = [_device(camera, account) for camera in api.cameras.values()]
        except CloudVerificationRequired:
            raise
        except Exception as exc:
            LOGGER.exception(
                "Eufy-Gerätesuche fehlgeschlagen | debug_id=%s error_type=%s",
                debug_id,
                type(exc).__name__,
            )
            raise CloudConnectionError(f"{_error_message(exc)} (Debug-ID: {debug_id})") from exc
        LOGGER.info(
            "Eufy-Gerätesuche erfolgreich | debug_id=%s devices=%s rtsp_streams=%s",
            debug_id,
            len(devices),
            sum(device.manual_stream_uri is not None for device in devices),
        )
        return devices


def _client_session():
    try:
        from aiohttp import ClientSession
    except ImportError as exc:
        raise CloudConnectionError("aiohttp ist nicht installiert") from exc
    return ClientSession()


async def _login(account: dict[str, Any], session: Any, debug_id: str = "unknown") -> Any:
    try:
        from eufy_security import API, InvalidCredentialsError
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
    challenge_key = _challenge_key(account, email, country)
    pending = _get_pending_challenge(challenge_key) if verification_code else None
    if verification_code and pending is None:
        LOGGER.warning(
            "Veralteter Eufy-Bestätigungscode verworfen; neue Challenge wird angefordert | "
            "debug_id=%s challenge=%s",
            debug_id,
            challenge_key,
        )
        verification_code = ""
    if pending is None:
        login_session = _EufyLoginSession(session, verification_code, debug_id)
        api = API(email, password, login_session, country)
    else:
        api = pending.api
        login_session = _EufyLoginSession(
            session,
            verification_code,
            debug_id,
            temporary_token=pending.temporary_token,
        )
        # pyeufysecurity does not expose a session setter. Rebinding here keeps
        # the original ECDH key while replacing the closed HTTP session.
        api._session = login_session
        LOGGER.debug(
            "Eufy-Code-Sitzung fortgesetzt | debug_id=%s challenge=%s",
            debug_id,
            challenge_key,
        )
    try:
        await api.async_authenticate()
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
        temporary_token = _temporary_token(login_session)
        _store_pending_challenge(challenge_key, api, temporary_token)
        LOGGER.debug(
            "Eufy-Code-Sitzung gespeichert | debug_id=%s challenge=%s ttl_seconds=%s",
            debug_id,
            challenge_key,
            CHALLENGE_TTL_SECONDS,
        )
        raise CloudVerificationRequired(
            "Eufy hat einen Bestätigungscode per E-Mail gesendet. Bitte eingeben, "
            "um die Anmeldung abzuschließen.",
            field_key="verification_code",
        ) from exc
    await api.async_update_device_info()
    if verification_code:
        await _trust_device(api, verification_code, debug_id)
        _remove_pending_challenge(challenge_key)
    return api


def _challenge_key(account: dict[str, Any], email: str, country: str) -> str:
    account_id = str(account.get("id") or "new")
    fingerprint = sha256(f"{email.lower()}|{country}".encode()).hexdigest()[:12]
    return f"{account_id}:{fingerprint}"


def _temporary_token(session: "_EufyLoginSession") -> str:
    auth_data = session.login_response.get("data") or {}
    token = str(auth_data.get("auth_token") or "")
    if not token:
        raise CloudConnectionError("Eufy hat für die Code-Sitzung keinen temporären Token geliefert")
    return token


def _store_pending_challenge(key: str, api: Any, temporary_token: str) -> None:
    with _PENDING_CHALLENGES_LOCK:
        _PENDING_CHALLENGES[key] = _PendingChallenge(
            api=api,
            temporary_token=temporary_token,
            expires_at=monotonic() + CHALLENGE_TTL_SECONDS,
        )


def _get_pending_challenge(key: str) -> _PendingChallenge | None:
    with _PENDING_CHALLENGES_LOCK:
        pending = _PENDING_CHALLENGES.get(key)
        if pending is not None and pending.expires_at <= monotonic():
            _PENDING_CHALLENGES.pop(key, None)
            return None
        return pending


def _remove_pending_challenge(key: str) -> None:
    with _PENDING_CHALLENGES_LOCK:
        _PENDING_CHALLENGES.pop(key, None)


class _EufyLoginSession:
    """Injects Eufy's 2FA code without modifying the third-party package."""

    def __init__(
        self,
        session: Any,
        verification_code: str,
        debug_id: str = "unknown",
        temporary_token: str = "",
    ) -> None:
        self.raw_session = session
        self.verification_code = verification_code
        self.debug_id = debug_id
        self.temporary_token = temporary_token
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
        if self.temporary_token:
            headers = dict(kwargs.get("headers") or {})
            headers["x-auth-token"] = self.temporary_token
            kwargs["headers"] = headers
        kwargs["json"] = payload
        return _CapturedLoginRequest(request(url, **kwargs), self, "login")

    def get(self, url: str, **kwargs: Any):
        return _CapturedLoginRequest(
            self.raw_session.get(url, **kwargs), self, "domain_lookup"
        )

    def request(self, method: str, url: str, **kwargs: Any):
        step = url.split("/", 3)[-1] if "/" in url else url
        return _CapturedLoginRequest(
            self.raw_session.request(method, url, **kwargs), self, step
        )


class _CapturedLoginRequest:
    def __init__(self, request: Any, session: _EufyLoginSession, step: str) -> None:
        self.request = request
        self.session = session
        self.step = step

    async def __aenter__(self):
        response = await self.request.__aenter__()
        return _CapturedLoginResponse(response, self.session, self.step)

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any):
        return await self.request.__aexit__(exc_type, exc, traceback)


class _CapturedLoginResponse:
    def __init__(
        self, response: Any, session: _EufyLoginSession, step: str = "login"
    ) -> None:
        self.response = response
        self.session = session
        self.step = step

    def __getattr__(self, name: str) -> Any:
        return getattr(self.response, name)

    @property
    def headers(self) -> Any:
        headers = self.response.headers
        if any(str(key).lower() == "content-type" for key in headers):
            return headers
        # Eufy's successful 2FA response can omit Content-Type even though the
        # body is JSON. pyeufysecurity otherwise rejects it before parsing.
        return {**headers, "Content-Type": "application/json"}

    async def json(self, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("content_type", None)
        data = await self.response.json(*args, **kwargs)
        _log_response_summary(
            debug_id=self.session.debug_id,
            step=self.step,
            response=self.response,
            data=data,
        )
        if not isinstance(data, dict):
            raise CloudConnectionError(
                f"Eufy-Antwort im Schritt '{self.step}' ist kein JSON-Objekt "
                f"(HTTP {getattr(self.response, 'status', '?')}, Typ {type(data).__name__})"
            )
        if self.step == "login" and data.get("code") == 0 and not isinstance(data.get("data"), dict):
            raise CloudConnectionError(
                "Eufy-Anmeldung lieferte keine Kontodaten "
                f"(HTTP {getattr(self.response, 'status', '?')}, Eufy-Code 0, "
                f"data={type(data.get('data')).__name__})"
            )
        if isinstance(data, dict):
            self.session.login_response = data
        return data


def _log_response_summary(*, debug_id: str, step: str, response: Any, data: Any) -> None:
    raw_headers = getattr(response, "headers", {})
    content_type = str(raw_headers.get("Content-Type") or "<fehlt>")
    code = data.get("code") if isinstance(data, dict) else None
    message = _redact_debug_text(data.get("msg")) if isinstance(data, dict) else ""
    data_type = type(data.get("data")).__name__ if isinstance(data, dict) else type(data).__name__
    LOGGER.debug(
        "Eufy-API-Antwort | debug_id=%s step=%s http_status=%s content_type=%s "
        "eufy_code=%s message=%r data_type=%s",
        debug_id,
        step,
        getattr(response, "status", "?"),
        content_type,
        code,
        message,
        data_type,
    )


def _redact_debug_text(value: Any) -> str:
    text = str(value or "")[:240]
    return EMAIL_PATTERN.sub("<E-Mail entfernt>", text)


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
        _log_response_summary(
            debug_id=session.debug_id,
            step="send_verification_code",
            response=response,
            data=result,
        )
    if not isinstance(result, dict) or result.get("code") != 0:
        message = result.get("msg") if isinstance(result, dict) else "unbekannter Fehler"
        raise CloudConnectionError(
            f"Eufy-Bestätigungscode konnte nicht angefordert werden: {message}"
        )
    LOGGER.info(
        "Eufy-Bestätigungscode angefordert | debug_id=%s delivery=email",
        session.debug_id,
    )


async def _trust_device(api: Any, verification_code: str, debug_id: str) -> None:
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
    LOGGER.info("Eufy-Client als vertrauenswürdig registriert | debug_id=%s", debug_id)


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
