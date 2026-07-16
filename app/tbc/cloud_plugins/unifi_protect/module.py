from __future__ import annotations

from typing import Any

from tbc_cloud_api import CloudAccountModule, CloudConnectionError, CloudDevice


class UnifiProtectCloudModule(CloudAccountModule):
    """Discovers UniFi Protect cameras through a controller login (local IP or ui.com cloud host).

    Reuses TBC's existing manual-RTSP `ubiquiti` camera module downstream:
    uiprotect resolves each camera channel that has RTSP explicitly enabled
    in Protect down to a ready-to-use rtsp:// URI, so no dedicated
    CameraModule is needed for UniFi Protect - see docs/cloud-accounts.md.
    """

    async def test_connection(self, account: dict[str, Any]) -> str:
        client = _client(account)
        try:
            bootstrap = await client.update()
        except Exception as exc:
            raise CloudConnectionError(_error_message(exc)) from exc
        finally:
            await client.close_session()
        nvr = bootstrap.nvr
        return f"Connected to {nvr.name} (UniFi Protect {nvr.version}, {len(bootstrap.cameras)} camera(s))"

    async def discover_devices(self, account: dict[str, Any]) -> list[CloudDevice]:
        client = _client(account)
        try:
            bootstrap = await client.update()
        except Exception as exc:
            raise CloudConnectionError(_error_message(exc)) from exc
        finally:
            await client.close_session()
        devices: list[CloudDevice] = []
        for camera in bootstrap.cameras.values():
            channel = next(
                (channel for channel in camera.channels if channel.is_rtsp_enabled and channel.rtsp_url),
                None,
            )
            devices.append(
                CloudDevice(
                    external_id=str(camera.id),
                    name=str(camera.name or camera.market_name or camera.id),
                    model=camera.market_name or camera.type,
                    online=bool(camera.is_connected),
                    manual_stream_uri=channel.rtsp_url if channel else None,
                    suggested_module_key="ubiquiti",
                )
            )
        return devices


def _client(account: dict[str, Any]) -> Any:
    try:
        from uiprotect import ProtectApiClient
    except ImportError as exc:
        raise CloudConnectionError("uiprotect is not installed") from exc

    host = str(account.get("host") or "").strip()
    if not host:
        raise CloudConnectionError("Host is required (controller IP or <id>.ui.com)")
    return ProtectApiClient(
        host,
        int(account.get("port") or 443),
        str(account.get("identifier") or ""),
        str(account.get("secret") or ""),
        verify_ssl=bool(account.get("verify_ssl")),
        store_sessions=False,
    )


def _error_message(exc: Exception) -> str:
    try:
        from uiprotect.exceptions import NotAuthorized
    except ImportError:
        return f"Connection failed: {exc}"
    if isinstance(exc, NotAuthorized):
        return (
            "Sign-in failed: incorrect username or password. If two-factor authentication is "
            "enabled for this account: this plugin does not support 2FA codes (the underlying "
            "uiprotect library has no interface for it) - please create a separate local "
            "account without 2FA."
        )
    return f"Connection failed: {exc}"


def create_module():
    return UnifiProtectCloudModule()
