"""ONVIF camera discovery via WS-Discovery (stdlib only).

Sends a single WS-Discovery Probe for NetworkVideoTransmitter to the standard
multicast group 239.255.255.250:3702 and collects ProbeMatch responses until
the timeout elapses. ONVIF-conformant cameras are required to answer this
probe; devices with ONVIF discovery disabled (or on another subnet - multicast
does not cross routers) simply won't appear.
"""
from __future__ import annotations

import socket
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass

MULTICAST_GROUP = "239.255.255.250"
MULTICAST_PORT = 3702
_WSD_NS = "http://schemas.xmlsoap.org/ws/2005/04/discovery"

_PROBE_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
            xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
            xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <e:Header>
    <w:MessageID>uuid:{message_id}</w:MessageID>
    <w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
    <w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
  </e:Header>
  <e:Body>
    <d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe>
  </e:Body>
</e:Envelope>"""


@dataclass(frozen=True)
class DiscoveredCamera:
    host: str
    onvif_port: int
    name: str
    hardware: str
    xaddr: str


def build_probe_message(message_id: str | None = None) -> bytes:
    return _PROBE_TEMPLATE.format(message_id=message_id or uuid.uuid4()).encode("utf-8")


def parse_probe_response(payload: bytes, sender_ip: str) -> list[DiscoveredCamera]:
    """Parse one WS-Discovery response datagram into discovered cameras.

    Tolerant by design: a malformed or non-ONVIF response yields an empty list
    instead of raising, since arbitrary WS-Discovery speakers (printers,
    Windows hosts) share the same multicast group.
    """
    try:
        root = ET.fromstring(payload.decode("utf-8", errors="replace"))
    except ET.ParseError:
        return []
    cameras: list[DiscoveredCamera] = []
    for match in root.iter(f"{{{_WSD_NS}}}ProbeMatch"):
        xaddrs_el = match.find(f"{{{_WSD_NS}}}XAddrs")
        scopes_el = match.find(f"{{{_WSD_NS}}}Scopes")
        xaddrs = (xaddrs_el.text or "").split() if xaddrs_el is not None else []
        scopes = (scopes_el.text or "").split() if scopes_el is not None else []
        if not xaddrs:
            continue
        # A device may advertise several XAddrs (IPv4/IPv6/hostname); prefer the
        # one matching the address it actually answered from.
        xaddr = next((candidate for candidate in xaddrs if sender_ip in candidate), xaddrs[0])
        parsed = urllib.parse.urlsplit(xaddr)
        host = parsed.hostname or sender_ip
        port = parsed.port or 80
        cameras.append(
            DiscoveredCamera(
                host=host,
                onvif_port=port,
                name=_scope_value(scopes, "name") or host,
                hardware=_scope_value(scopes, "hardware"),
                xaddr=xaddr,
            )
        )
    return cameras


def _scope_value(scopes: list[str], key: str) -> str:
    prefix = f"onvif://www.onvif.org/{key}/"
    for scope in scopes:
        if scope.startswith(prefix):
            return urllib.parse.unquote(scope[len(prefix):])
    return ""


def discover_onvif_cameras(timeout_seconds: float = 3.0) -> list[DiscoveredCamera]:
    """Blocking multicast probe; call via asyncio.to_thread from route handlers."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(0.5)
        sock.bind(("", 0))
        sock.sendto(build_probe_message(), (MULTICAST_GROUP, MULTICAST_PORT))

        found: dict[str, DiscoveredCamera] = {}
        import time

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                payload, (sender_ip, _sender_port) = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            for camera in parse_probe_response(payload, sender_ip):
                found.setdefault(f"{camera.host}:{camera.onvif_port}", camera)
        return sorted(found.values(), key=lambda camera: camera.host)
    finally:
        sock.close()
