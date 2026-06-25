# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `Vdsd.send_identify()` async method — sends `VDC_SEND_IDENTIFY` (type 22, vDC → vdSM) as a fire-and-forget notification when the user physically identifies a device (e.g. presses a pairing button on the hardware). The vdSM uses the incoming dSUID to associate the physical device with a pairing or zone-assignment request. No-op if the device is not yet announced or has no active session.
- `MAX_SUPPORTED_API_VERSION: int = 4` constant — upper bound of the accepted `hello` API version range. Versions above this are rejected with `ERR_INCOMPATIBLE_API`.
- `DeviceLifecycleState` enum with five states (`ACTIVE`, `INACTIVE`, `MAINTENANCE`, `ERROR`, `REMOVED`) for expressing device health from library user code.
- `Vdsd.set_lifecycle_state(state: DeviceLifecycleState)` async method — sets the lifecycle state and handles all vdSM communication automatically: pushes `active` property changes to dSS, suppresses pong responses for non-ACTIVE devices, and triggers `VDC_SEND_VANISH` for `REMOVED` devices (re-triggered on every subsequent ping).
- `Vdsd.lifecycle_state` read-only property — returns the current `DeviceLifecycleState`.
- `VdcSession.set_presence_checker(checker)` method — registers an async `(dsuid: str) -> bool` callback that gates pong responses. Pass `None` to clear. Used internally by `VdcHost`; can be used directly in custom session setups.

### Changed
- `VdcSession` `hello` handshake now enforces both a lower and upper API version bound (`SUPPORTED_API_VERSION ≤ api_version ≤ MAX_SUPPORTED_API_VERSION`). Versions above the maximum are rejected with `ERR_INCOMPATIBLE_API` and the session is closed.
- Re-hello from the **same vdSM dSUID** during an active session resets the session state (pending requests cancelled, counters zeroed) and fires `on_hello` again so all vDCs and devices are re-announced. This matches the vDC API specification and handles the case where the vdSM lost track of the still-open connection.
- Re-hello from a **different vdSM dSUID** during an active session is now rejected with `ERR_SERVICE_NOT_AVAILABLE` — the existing session is preserved. Previously the session would accept any hello unconditionally.

### Removed
- `Vdsd.active` setter (write access via `vdsd.active = True/False`). The read-only `active` property is retained (derived from `lifecycle_state`). **Migration:** replace `vdsd.active = False` with `await vdsd.set_lifecycle_state(DeviceLifecycleState.INACTIVE)`.

## [0.8.9] - 2026-06-15

### Added
- `on_disconnect` callback parameter on `VdcHost.start()`: an optional async callback fired when the vdSM TCP connection is lost unexpectedly (network drop, dSS restart, etc.). Receives `(host: VdcHost, reason: Exception | None)` — `reason` is the exception that caused the disconnect, or `None` for a clean EOF / bye. The callback is **not** called when `host.stop()` initiates the disconnect.
- `VdcSession.disconnect_reason: Exception | None` attribute — exposed after `session.run()` returns so callers can inspect what ended the session.
- `shadeprops` and `motiontimefins` model features are no longer blocked: they have been moved from the unsupported set to the "not tested / add manually" category. Add them via `add_model_feature()` on grey shade devices that expose motor timing `outputSettings` fields.
- `FCU_OPERATION_MODE` channel type added to `OutputChannelType` enum and `CHANNEL_SPECS`, with correct enum `values` (`off`, `heating`, `cooling`, `fanOnly`, `dry`, `auto`).
- `COLOR_CLASS_STANDARD_CHANNEL` mapping added to `output_channel.py` — maps application group ID to the standard `OutputChannelType` for that group (e.g. group 1 → `BRIGHTNESS`, group 2 → `SHADE_POSITION_OUTSIDE`). Used for resolving channel-type key `"0"` per ds-basics §7.
- `values` container emitted in `channelDescriptions` for all enum/discrete channels: `AIR_FLOW_DIRECTION`, `AIR_LOUVER_AUTO`, `AIR_FLOW_AUTO`, `POWER_STATE`, `FCU_OPERATION_MODE`. String keys, string values (e.g. `{"0": "off", "1": "on"}`).
- `OutputChannel` and `Output.add_channel()` now accept `siunit`, `symbol`, and `enum_values` parameters for fully custom channel types. For predefined types the spec is always authoritative; for device-specific channel types these parameters control what is emitted in `channelDescriptions` and what is persisted to YAML.
- `_ChannelCompatDict` backward-compatibility layer: `getProperty` requests for `channelDescriptions`, `channelSettings`, and `channelStates` now resolve numeric keys (channel type decimal strings such as `"1"`, and the special `"0"` alias for the primary channel) in addition to the canonical channel name keys, covering API v2 and legacy lookup paths.

### Fixed
- Channel container keys (`channelDescriptions`, `channelSettings`, `channelStates`) for **all** output functions now use the **channel name string** (e.g. `"shadePositionOutside"`, `"brightness"`) as the outer key, matching the vDC API v3+ wire format. Includes `POSITIONAL`, `DIMMER_COLOR_TEMP`, and `FULL_COLOR_DIMMER`. Numeric key backward-compatibility is handled transparently via `_ChannelCompatDict`.
- Removed S2 awning workaround in `examples/example_shading.py` (`name="0"` override); the example now uses the standard `add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)` call.
- `modelFeatures` property now emitted in canonical `ModelFeatureId` enum order instead of alphabetical order, matching the vDC API specification.
- `movingState` removed from `outputState` — it was not part of the vDC API specification and was never emitted per spec.
- `waterFlow` channel name corrected (`WATER_FLOW_RATE` spec name was missing; now `"waterFlow"`).
- `outputSettings` shadow timing fields (`openTime`, `closeTime`, `angleOpenTime`, `angleCloseTime`, `stopDelayTime`) are now correctly gated on `primaryGroup == 2` (shade/blind devices), not emitted for other device classes.
- `outputSettings` light-specific fields (`minBrightness`, `dimTimeUp`, `dimTimeDown`, `dimTimeUpAlt1`, `dimTimeDownAlt1`, `dimTimeUpAlt2`, `dimTimeDownAlt2`) are correctly gated on `primaryGroup == 1`.
- `outputSettings` climate fields (`heatingSystemCapability`, `heatingSystemType`) are correctly gated on `primaryGroup == 3`.

## [0.8.8] - 2026-05-30

### Added
- `ChannelSpec` now carries `siunit` and `symbol` fields; all built-in channel specs are populated with the appropriate SI unit and symbol (e.g. `percent`/`%` for brightness/shade, `degree`/`°` for hue, `reciprocal megakelvin`/`mired` for color temperature). These are emitted in `channelDescriptions` responses to match the vDC API wire format and fix grey-device validation errors on dSS.
- Shadow motor timing fields `openTime`, `closeTime`, `angleOpenTime`, `angleCloseTime`, `stopDelayTime` added to `outputSettings` for shade devices. dSS reads and writes these to configure motor travel timing.
- `transitionTime` field (float, seconds) added to `outputState`, per the vDC API specification.
- `movingState` (integer) added to `outputState` for shade/blind outputs: `0` = idle, `1` = moving open/up, `-1` = moving closed/down. Matches the vDC API shade output wire format.
- Unknown `setProperty outputSettings` keys are now stored in `Output._extra_settings` and returned in future `get_settings_properties()` responses instead of being silently dropped.

### Fixed
- Shade channel resolution corrected from 8-bit (`100/255 ≈ 0.392`) to 16-bit (`100/65536 ≈ 0.00153`), per the vDC API specification. Affects `SHADE_POSITION_OUTSIDE`, `SHADE_POSITION_INDOOR`, `SHADE_OPENING_ANGLE_OUTSIDE`, `SHADE_OPENING_ANGLE_INDOOR`.
- All channel container keys (`channelDescriptions`, `channelSettings`, `channelStates` in GET responses and push notifications) now use the channel's **dsIndex** as string key (e.g. `"0"`, `"1"`), per the vDC API specification. The 0.8.6 change that switched to channel name keys is reverted; name-based lookup in `vdc_host.py` for incoming `setOutputChannelValue` notifications is unchanged.

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

[0.8.9]: https://github.com/KarlKiel/pyDSvDCAPI/compare/v0.8.8...v0.8.9
[0.8.8]: https://github.com/KarlKiel/pyDSvDCAPI/compare/v0.8.7...v0.8.8
[0.8.7]: https://github.com/KarlKiel/pyDSvDCAPI/compare/v0.8.6...v0.8.7
[0.8.6]: https://github.com/KarlKiel/pyDSvDCAPI/compare/v0.8.4...v0.8.6
[0.8.4]: https://github.com/KarlKiel/pyDSvDCAPI/compare/v0.8.3...v0.8.4
[0.8.3]: https://github.com/KarlKiel/pyDSvDCAPI/compare/v0.8.1...v0.8.3
[0.8.1]: https://github.com/KarlKiel/pyDSvDCAPI/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/KarlKiel/pyDSvDCAPI/compare/v0.1.0...v0.8.0
[0.1.0]: https://github.com/KarlKiel/pyDSvDCAPI/releases/tag/v0.1.0
