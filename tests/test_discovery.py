import unittest

from app.tbc.discovery import build_probe_message, parse_probe_response

PROBE_MATCH = b"""<?xml version="1.0" encoding="UTF-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope"
                   xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
                   xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
  <SOAP-ENV:Body>
    <d:ProbeMatches>
      <d:ProbeMatch>
        <wsa:EndpointReference><wsa:Address>urn:uuid:1234</wsa:Address></wsa:EndpointReference>
        <d:Types>dn:NetworkVideoTransmitter</d:Types>
        <d:Scopes>onvif://www.onvif.org/type/video_encoder onvif://www.onvif.org/name/Front%20Door onvif://www.onvif.org/hardware/RLC-810A</d:Scopes>
        <d:XAddrs>http://192.168.1.50:8000/onvif/device_service http://[fe80::1]:8000/onvif/device_service</d:XAddrs>
        <d:MetadataVersion>1</d:MetadataVersion>
      </d:ProbeMatch>
    </d:ProbeMatches>
  </SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""


class ParseProbeResponseTests(unittest.TestCase):
    def test_parses_host_port_name_and_hardware(self):
        cameras = parse_probe_response(PROBE_MATCH, "192.168.1.50")
        self.assertEqual(len(cameras), 1)
        camera = cameras[0]
        self.assertEqual(camera.host, "192.168.1.50")
        self.assertEqual(camera.onvif_port, 8000)
        self.assertEqual(camera.name, "Front Door")
        self.assertEqual(camera.hardware, "RLC-810A")

    def test_prefers_the_xaddr_matching_the_sender_ip(self):
        payload = PROBE_MATCH.replace(
            b"http://192.168.1.50:8000/onvif/device_service http://[fe80::1]:8000/onvif/device_service",
            b"http://10.0.0.9:8000/onvif/device_service http://192.168.1.50:8000/onvif/device_service",
        )
        cameras = parse_probe_response(payload, "192.168.1.50")
        self.assertEqual(cameras[0].host, "192.168.1.50")

    def test_defaults_port_80_when_xaddr_has_no_port(self):
        payload = PROBE_MATCH.replace(
            b"http://192.168.1.50:8000/onvif/device_service http://[fe80::1]:8000/onvif/device_service",
            b"http://192.168.1.50/onvif/device_service",
        )
        cameras = parse_probe_response(payload, "192.168.1.50")
        self.assertEqual(cameras[0].onvif_port, 80)

    def test_non_onvif_or_malformed_datagrams_yield_nothing(self):
        self.assertEqual(parse_probe_response(b"not xml at all", "192.168.1.7"), [])
        self.assertEqual(
            parse_probe_response(b"<?xml version='1.0'?><Envelope></Envelope>", "192.168.1.7"), []
        )

    def test_probe_message_targets_network_video_transmitters(self):
        message = build_probe_message("test-id").decode("utf-8")
        self.assertIn("dn:NetworkVideoTransmitter", message)
        self.assertIn("uuid:test-id", message)
        self.assertIn("http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe", message)


if __name__ == "__main__":
    unittest.main()
