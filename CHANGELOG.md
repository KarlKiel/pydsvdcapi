# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.3] - 2026-05-15

### Added
- `scanDevices` GenericRequest handler: when the dSS configurator triggers
  "Re-register devices", pydsvdcapi now resets announcement flags and
  re-announces the addressed vDC and all its devices automatically.
  Version-suffixed variants such as `scanDevices/6` are accepted.

### Fixed
- Sphinx `docs/conf.py` now derives the release version dynamically from
  `pydsvdcapi.__version__` instead of a hardcoded string.

## [0.8.1] - 2026-05-14

### Fixed
- AKM (Aktor-Kontakt-Modul) input handling: `AKMINPUT` and `AKMDELAY` model
  features are now correctly marked as unsupported in device announcements.
- AKM input behavior adjustments for proper integration with dSS firmware.
- `zoneId = NULL` behavior correction in device address handling.
- Code formatting to comply with ruff linter standards (line length, imports).
- Minor enum documentation clarifications.

### Changed
- Updated enum documentation for button input modes and AKM-related features.
- Enhanced dSS Configurator UI composition documentation.

## [0.8.0] - 2026-05-04

### Changed
- Renamed Python package from `pyDSvDCAPI` to `pydsvdcapi` (PEP 8 lowercase).
- Moved package source to `src/pydsvdcapi/` (src layout, per PyPA recommendation).
- Added `py.typed` marker (PEP 561) — the package is now recognised as typed by mypy.
- Extended `pyproject.toml` with `[project.optional-dependencies]`, ruff, mypy,
  and coverage tool configuration.

### Added
- Device template system (`DeviceTemplate`, `TemplateNotConfiguredError`,
  `AnnouncementNotReadyError`) for saving and loading structural device snapshots.
- Value converter support on `SensorInput`, `BinaryInput`, `OutputChannel`,
  `DeviceState`, and `DeviceProperty` (`uplinkConverter` / `downlinkConverter`
  code snippets stored in YAML).
- `Vdsd.derive_model_features()` — automatically derives `modelFeatures` flags
  from configured components before announcement.
- `Vdc.save_template()` and `Vdc.load_template()` with configurable
  `template_path` on the `Vdc` constructor.

## [0.1.0] - 2025-01-01

### Added
- Initial release.
- `VdcHost` — manages the TCP connection and session lifecycle.
- `Vdc` — virtual Device Connector with full common-property support.
- `Device` / `Vdsd` — physical device and virtual dS device abstraction.
- Component types: `BinaryInput`, `ButtonInput`, `SensorInput`,
  `DeviceEvent`, `DeviceState`, `DeviceProperty`, `Output`, `OutputChannel`.
- Action system: `DeviceActionDescription`, `StandardAction`, `CustomAction`,
  `DynamicAction`.
- Persistence: YAML-based state store (`PropertyStore`) with debounced auto-save.
- `DsUid` — dSUID encoding/decoding with multiple creation strategies.
- Property handling helpers (`build_get_property_response`, etc.).

[0.8.3]: https://github.com/KarlKiel/pyDSvDCAPI/compare/v0.8.1...v0.8.3
[0.8.1]: https://github.com/KarlKiel/pyDSvDCAPI/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/KarlKiel/pyDSvDCAPI/compare/v0.1.0...v0.8.0
[0.1.0]: https://github.com/KarlKiel/pyDSvDCAPI/releases/tag/v0.1.0
