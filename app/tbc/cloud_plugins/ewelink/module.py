from __future__ import annotations

from typing import Any

from tbc_cloud_api import CloudAccountModule, CloudConnectionError, CloudDevice


class EwelinkCloudModule(CloudAccountModule):
    """Discovers SONOFF devices through the official eWeLink/CoolKit Open Platform account API.

    Unlike Eufy or UniFi Protect, this official API does not expose a
    device's local IP address or RTSP link at all - eWeLink only generates
    that link inside the app itself, once RTSP is enabled per camera (see
    the existing `sonoff` manual-RTSP camera module). discover_devices()
    therefore only reports device names/models/online state here;
    `manual_stream_uri` stays empty and devices cannot be auto-imported as
    cameras. See docs/cloud-accounts.md.
    """

    async def test_connection(self, account: dict[str, Any]) -> str:
        client = await _login(account)
        try:
            devices = await client.get_thing_list()
        except Exception as exc:
            raise CloudConnectionError(_error_message(exc)) from exc
        finally:
            await client.close()
        return f"Mit eWeLink verbunden ({len(devices)} Gerät(e))"

    async def discover_devices(self, account: dict[str, Any]) -> list[CloudDevice]:
        client = await _login(account)
        try:
            devices = await client.get_thing_list()
        except Exception as exc:
            raise CloudConnectionError(_error_message(exc)) from exc
        finally:
            await client.close()
        return [_device(device) for device in devices]


async def _login(account: dict[str, Any]) -> Any:
    try:
        from ewelink import EWeLink
        from ewelink.types import AppCredentials, EmailUserCredentials
    except ImportError as exc:
        raise CloudConnectionError("ewelink ist nicht installiert") from exc
    app_id = str(account.get("app_id") or "").strip()
    app_secret = str(account.get("app_secret") or "").strip()
    email = str(account.get("email") or "").strip()
    password = str(account.get("password") or "")
    if not app_id or not app_secret:
        raise CloudConnectionError(
            "App-ID und App-Secret sind erforderlich (kostenlose Registrierung unter dev.ewelink.cc)"
        )
    if not email or not password:
        raise CloudConnectionError("E-Mail-Adresse und Passwort sind erforderlich")
    client = EWeLink(
        AppCredentials(id=app_id, secret=app_secret),
        EmailUserCredentials(email=email, password=password),
    )
    try:
        await client.login()
    except Exception as exc:
        await client.close()
        raise CloudConnectionError(_error_message(exc)) from exc
    return client


def _device(device: Any) -> CloudDevice:
    extra = getattr(device, "extra", None)
    model = getattr(extra, "model", None) if extra is not None else None
    return CloudDevice(
        external_id=str(device.deviceid),
        name=str(device.name or device.deviceid),
        model=model or getattr(device, "product_model", None) or None,
        online=bool(device.online),
        manual_stream_uri=None,
        suggested_module_key="sonoff",
    )


def _error_message(exc: Exception) -> str:
    try:
        from ewelink.ewelink import EWeLinkError
    except ImportError:
        return f"eWeLink-Verbindung fehlgeschlagen: {exc}"
    if isinstance(exc, EWeLinkError):
        return f"eWeLink-Anmeldung fehlgeschlagen: {exc.msg} (Fehlercode {exc.error})"
    return f"eWeLink-Verbindung fehlgeschlagen: {exc}"


def create_module():
    return EwelinkCloudModule()
