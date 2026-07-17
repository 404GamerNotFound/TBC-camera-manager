## Summary

<!-- Describe the user-visible result and why the change is needed. -->

## Technical implementation

<!-- Describe the main components, data flow, migrations, and important design decisions. -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Camera or cloud integration
- [ ] Refactoring
- [ ] Documentation or translation
- [ ] Dependency, container, or CI change
- [ ] Breaking change

## Verification

<!-- List the checks you ran and any relevant manual test setup. -->

- [ ] `pytest -q`
- [ ] `python -m unittest discover -s tests`
- [ ] `python -m compileall app tests`
- [ ] `docker compose config`
- [ ] Relevant manual or plugin-specific tests

## Security and privacy

- [ ] No credentials, tokens, private stream URLs, serial numbers, or personal footage are included.
- [ ] Authorization and per-camera access checks remain enforced for new routes.
- [ ] Logs and error messages redact sensitive values.
- [ ] Database migrations and rollback or recovery behavior were considered.
- [ ] Third-party code, assets, models, and dependencies have compatible licenses.

## Documentation and compatibility

- [ ] User-facing documentation was updated where necessary.
- [ ] User-facing text was added to every supported locale.
- [ ] `tbc_camera_manager/CHANGELOG.md` was updated for a user-visible change.
- [ ] `amd64`, `aarch64`, Docker Compose, and Home Assistant impact was considered.

## Screenshots or recordings

<!-- Add sanitized UI evidence when useful. Do not include identifying camera footage. -->

## Related issues

<!-- Example: Closes #123 -->
