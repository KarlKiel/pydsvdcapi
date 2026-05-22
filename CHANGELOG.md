# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.7] - 2026-05-22

### Fixed
- `gen_device_properties_xls.py`: corrected `OutputUsage` schema annotation —
  values were documented as `0=ROOM 1=USER 2=OTHER`; correct mapping is
  `0=UNDEFINED 1=ROOM 2=OUTDOORS`, matching the `OutputUsage` enum.

## [0.8.6] - 2026-05-22

### Fixed
- `channelDescriptions`, `channelSettings`, and `channelStates` property trees
  now use the channel **name** (e.g. `"brightness"`, `"colortemp"`) as the
  element key instead of the numeric `dsIndex` string (`"0"`, `"1"`).  This
  matches what dSS expects and resolves `deviceOutputIndex:255` errors caused
  by dSS not recognising channels it had registered under integer-string keys.
- Push notifications for channel state changes use the channel name as the
  `channelStates` key, consistent with the above fix.
- `setOutputChannelValue` handler in `VdcHost` no longer attempts a numeric
  `dsIndex` lookup when resolving `channelId`; it looks up channels by name
  only (with the legacy integer-type fallback still in place).

## [0.8.4] - 2026-05-16

### Added
- Persistent `pendingVanish` list in `VdcHost`: dSUIDs of devices and vDCs
  removed while the session is offline are stored in YAML and flushed as
  `VDC_SEND_VANISH` messages to the vdSM on the next session connect, before
  re-announcing surviving vDCs.  vdSM-initiated removals (`VDSM_SEND_REMOVE`)
  are correctly excluded from the list.

### Fixed
- `examples/full_showcase.py`: removed erroneous `add_model_feature()` calls
  for `akminput`, `akmdelay` (both raise `ValueError` since 0.8.1), and an
  incorrectly placed `akmsensor` on D04 (which has only `SensorInput`s, not
  `BinaryInput`s).

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

[0.8.6]: https://github.com/KarlKiel/pyDSvDCAPI/compare/v0.8.4...v0.8.6
[0.8.4]: https://github.com/KarlKiel/pyDSvDCAPI/compare/v0.8.3...v0.8.4
[0.8.3]: https://github.com/KarlKiel/pyDSvDCAPI/compare/v0.8.1...v0.8.3
[0.8.1]: https://github.com/KarlKiel/pyDSvDCAPI/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/KarlKiel/pyDSvDCAPI/compare/v0.1.0...v0.8.0
[0.1.0]: https://github.com/KarlKiel/pyDSvDCAPI/releases/tag/v0.1.0
