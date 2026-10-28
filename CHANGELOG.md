# Changelog

All notable changes to ClipNest are recorded here. Entries are grouped by kind,
following the spirit of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

No version has been published yet, so no entry carries a release date.

## [0.1.0] — unreleased

First release candidate of the Windows x64 clipboard manager. Everything below
exists in the current source tree.

### Added

- Clipboard capture from `QClipboard.dataChanged` (no polling) into a local
  SQLite history; empty and whitespace-only content is ignored, consecutive
  duplicates are skipped, and text is truncated to 10,000 characters with a
  visible trimmed notice.
- Windows clipboard privacy markers read before any text is touched:
  `ExcludeClipboardContentFromMonitorProcessing`,
  `CanIncludeInClipboardHistory` and `CanUploadToCloudClipboard`, applied
  fail-closed.
- Best-effort sensitive-content detection with five rule families (private keys,
  provider API keys, credential assignments, one-time codes, card numbers) that
  refuses the capture and reports only the category.
- Encryption at rest through Windows DPAPI (schema version 2): snippets are
  stored as protected blobs, a tampered row fails to decrypt instead of
  returning corrupted text, and a plaintext history from an earlier build is
  migrated in one transaction with no plaintext backup left behind.
- A protected canary row so a history encrypted by another Windows account is
  refused and left byte-identical instead of being replaced.
- History limits: a configurable maximum of unpinned entries (default 500,
  range 10–5,000) plus an optional age limit in days (1–3,650, off by default).
  Pinned snippets are never trimmed by either limit.
- `PRAGMA secure_delete = ON` on every connection, with a `VACUUM` after a
  user-requested delete or clear, and no vacuum during automatic trimming.
- Snippet cards with type icon, preview, relative time and size, pin toggle and
  a detail panel offering **Copy again**, **Pin/Unpin** and **Delete**.
- Sidebar categories **All**, **Pinned**, **Text**, **Links** and **Code**, a
  search box, and dedicated empty, paused and error states.
- Pause monitoring that survives restarts, including a start-paused fallback
  when the saved pause value cannot be read.
- Clear-history confirmation that states pinned snippets are kept.
- System tray menu with Show ClipNest, Pause/Resume Monitoring, Clear Unpinned
  History and Quit; closing the window hides it while monitoring continues, and
  a lost tray icon restores close-to-quit so the app stays reachable.
- Settings page with Appearance (dark default, light available, applied
  immediately), History limits, Privacy state and the list of working
  shortcuts.
- In-window shortcuts: `Ctrl+K` for search and `Esc` to step back out of search,
  the search field and notifications.
- One-time notice on the first start that actually monitors, explaining that
  copied text is saved locally.
- `CLIPNEST_DATA_DIR` override for an absolute data directory, used to validate a
  packaged build without touching real history.
- PyInstaller one-folder build (`ClipNest.spec`, icon and Windows version
  resource) producing `ClipNest.exe` with no bundled database, preference file or
  user path.
- 444 headless tests, a release verifier that exercises real DPAPI and SQLite,
  and a disposable-database seeder for packaged-build checks.
- GitHub Actions workflow, configured to run the test suite on a Windows runner
  for pushes and pull requests (not yet executed: the repository is unpublished).

### Security

- No clipboard content is written to any log, notification or error message.
- Local-only operation: no account, no cloud sync, no analytics, no telemetry.
- Clipboard privacy markers are honoured before the text is read.
- A history that cannot be unlocked is reported, never silently replaced.

### Known limitations

- Sensitive detection is a heuristic, not a guarantee.
- Deletion is best effort; it is not forensic erasure.
- DPAPI protection is per Windows profile: losing the profile loses the history.
- Windows x64 only; the build was verified on a single Windows installation.
- No installer, no auto-start and no system-wide hotkey.
