# Security Policy

TBC Camera Manager processes camera credentials, live video, recordings, cloud
account tokens, and notification secrets. Please handle potential
vulnerabilities privately and avoid exposing real installations or footage.

## Supported versions

Security fixes are provided for the latest published release and the current
default branch. Older releases may not receive patches. Users should upgrade to
the latest release before reporting an issue that may already be resolved.

| Version | Supported |
| --- | --- |
| Latest release | Yes |
| Default branch | Yes |
| Older releases | No |

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability.

Use GitHub's
[private vulnerability reporting form](https://github.com/404GamerNotFound/TBC-camera-manager/security/advisories/new)
and include:

- The affected version or commit
- The vulnerable component and prerequisites
- Reproduction steps or a minimal proof of concept
- The expected security boundary and actual result
- Possible impact and suggested mitigation, if known
- Whether the report includes or requires access to sensitive data

Remove camera passwords, API keys, session cookies, cloud tokens, private RTSP
URLs, public IP addresses, and identifying footage. If sensitive material is
essential, ask the maintainers how to transfer it safely before sending it.

The maintainers will acknowledge a complete report as soon as reasonably
possible, investigate it, and coordinate disclosure and a fix with the reporter.
Please allow time for supported release images and Home Assistant packages to be
built before publishing technical details.

## Security expectations

- Change the default administrator password and configure a strong
  `TBC_SECRET_KEY` before exposing TBC outside a test network.
- Prefer a trusted reverse proxy with HTTPS or private VPN access.
- Restrict access to the data, recording, and plugin directories.
- Install camera, cloud, and theme packages only from trusted sources. Camera
  and cloud plugins execute with the same privileges as the TBC process.
- Keep TBC, its container image, the host, camera firmware, and reverse proxy up
  to date.

General hardening questions and non-sensitive bugs may be discussed in a normal
GitHub issue. Vulnerabilities in third-party packages should also be reported to
the affected upstream project when appropriate.
