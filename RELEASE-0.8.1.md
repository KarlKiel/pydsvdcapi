# Release 0.8.1 - Preparation Summary

**Release Date:** May 14, 2026  
**Previous Release:** 0.8.0 (May 4, 2026)

## Files Updated

✅ **pyproject.toml**
- Version: `0.8.0` → `0.8.1`

✅ **src/pydsvdcapi/__init__.py**
- `__version__`: `"0.8.0"` → `"0.8.1"`

✅ **CHANGELOG.md**
- Added new [0.8.1] section with release notes
- Added version comparison link: `v0.8.0...v0.8.1`

## Release Highlights

### Fixed
- **AKM Input Handling**: `AKMINPUT` and `AKMDELAY` model features are now correctly marked as unsupported in device announcements
- **AKM Behavior**: Adjustments for proper integration with dSS firmware
- **Zone ID Handling**: Fixed `zoneId = NULL` behavior in device address handling
- **Code Quality**: Format compliance with ruff linter standards (line length, imports)
- **Documentation**: Minor enum documentation clarifications

### Changed
- Updated enum documentation for button input modes and AKM-related features
- Enhanced dSS Configurator UI composition documentation

## Changes Since 0.8.0

- 11 commits merged (since v0.8.0 tag)
- Key improvements in AKM (Aktor-Kontakt-Modul) device support
- Enhanced documentation and code quality

## Pre-Release Verification

✅ Format check: PASSED (ruff format --check)  
✅ Lint check: PASSED (ruff check)  
✅ Version consistency: VERIFIED  
✅ CHANGELOG format: COMPLIANT (Keep a Changelog)  

## Next Steps for Release

1. **Create Git Tag**
   ```bash
   git tag -a v0.8.1 -m "Release 0.8.1: AKM fixes and documentation updates"
   git push origin v0.8.1
   ```

2. **Build Package**
   ```bash
   python -m build
   ```

3. **Publish to PyPI**
   ```bash
   python -m twine upload dist/*
   ```
   (The GitHub Actions workflow will automatically trigger on tag push)

4. **Create GitHub Release**
   - Copy CHANGELOG.md [0.8.1] section as release notes
   - Attach wheel and sdist from `dist/`

## Version Matrix

| Component | Old Version | New Version |
|-----------|------------|------------|
| pyproject.toml | 0.8.0 | 0.8.1 |
| __init__.py | 0.8.0 | 0.8.1 |
| Minimum Python | 3.10 | 3.10 (unchanged) |
| Supported Python | 3.10-3.13 | 3.10-3.13 (unchanged) |

## File Checksums (After Update)

Modified files ready for commit:
- `CHANGELOG.md` → 15 lines added, 0 removed
- `pyproject.toml` → 1 line changed
- `src/pydsvdcapi/__init__.py` → 1 line changed

---

**Status**: ✅ Ready for Release  
**Quality**: ✅ All checks passed
