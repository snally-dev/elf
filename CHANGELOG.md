# Changelog

Notable user-facing changes to elf are documented here.

## 1.2.0 — 2026-11-15

### Added

- Calendar-aware defaults for archived, active, and reduced-length Advent of Code events.
- Persistent private-leaderboard caching with the required 15-minute refresh interval.
- `elf doctor` for offline configuration, version, clock, and cache diagnostics.
- Account-scoped input and submission caches, atomic writes, private permissions, and safe legacy-cache migration.
- Cross-process protection for leaderboard refreshes, guess history, and answer submission.
- Exact server-provided submission cooldown deadlines, exposed as `SubmissionResult.retry_at`.
- Ruff, mypy, network-blocked tests, and Linux, macOS, and Windows CI coverage.

### Changed

- Default commands select the latest relevant puzzle outside December while explicit year and day arguments remain authoritative.
- Internally created HTTP clients now have explicit ownership and are closed reliably; injected clients remain caller-owned.
- JSON and user-provided text are emitted without Rich markup interpretation.
- Existing four-column guess histories are upgraded safely on their next write.

### Fixed

- Cache sharing between different Advent of Code accounts.
- Partial cache files and lost rows during interrupted or concurrent writes.
- Duplicate concurrent submissions and submissions to a locally known completed part.
- Authentication-page handling, malformed cache handling, historical calendar parsing, and several HTTP error messages.
- Windows startup failures on systems without an operating-system timezone database.

### Compatibility

- The documented top-level Python API remains compatible.
- Existing inputs and guess histories are preserved; legacy files remain available for manual recovery.
- `SubmissionResult.retry_at` is an additive optional field and is `None` outside cooldown responses.
