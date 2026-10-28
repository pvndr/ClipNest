# ClipNest

A local-only clipboard history manager for Windows, built with Python, PySide6 (Qt 6) and SQLite, with Windows DPAPI encryption at rest.

Copy text anywhere in Windows and ClipNest keeps it: browse the history in a sidebar, search it, pin what matters, and paste it back with one click. History survives restarts, never leaves the machine, and is encrypted with the current Windows account. ClipNest sits in the system tray, and no clipboard content is ever written to a log.

## Status

**Windows release candidate, not yet released.**

- Version `0.1.0`, Windows x64 only.
- 444 automated tests pass headless; the release candidate was verified on a single Windows x64 installation.
- A one-folder build (`ClipNest.exe` plus an `_internal` folder) has been produced and validated locally.
- Source code is available in the [public GitHub repository](https://github.com/pvndr/ClipNest).
- The initial commit is published, and the first [GitHub Actions CI run](https://github.com/pvndr/ClipNest/actions) completed successfully.
- No GitHub Release or downloadable binary has been published yet.
- Screenshots are not included yet: the only captures made so far come from a private verification run and are not published.

## Features

- **Capture.** Listens to the Windows clipboard (`QClipboard.dataChanged`, no polling) and stores copied plain text in SQLite. Empty or whitespace-only content is ignored, consecutive duplicates are skipped, and text is truncated to 10,000 characters with a visible "trimmed" notice.
- **Privacy markers respected.** Content that a source application marks as private is never read and never saved.
- **Sensitive-content filter.** Private keys, provider API keys, credential assignments, one-time codes and card numbers are refused before they reach the database (on by default, switchable in **Settings → Privacy**).
- **Encrypted at rest.** Snippets are protected with Windows DPAPI before they are written; the database never holds them as readable text.
- **History limits.** A configurable maximum number of unpinned entries (default 500, 10–5,000) plus an optional age limit in days (off by default). Pinned snippets are never trimmed.
- **Pinning, search and categories.** Sidebar categories **All**, **Pinned**, **Text**, **Links** and **Code**, backed by a small heuristic classifier.
- **Cards and detail panel.** Each snippet shows a type icon, preview, relative time and size; selecting one opens the full text with **Copy again**, **Pin/Unpin** and **Delete**.
- **Pause monitoring.** Stops recording without disconnecting, and the choice survives a restart.
- **System tray.** Show, Pause/Resume, Clear Unpinned History and Quit. Closing the window hides it and monitoring keeps running; *Quit* is the real exit.
- **Settings page.** Appearance (dark/light, applied immediately), history limits, privacy state and the list of working shortcuts.
- **Keyboard shortcuts** while the window is focused: `Ctrl+K` for search, `Esc` to step back out of search, the search field and a notification.

Deeper implementation notes — clipboard marker formats, detection rules, encryption and migration internals, preference keys, build pitfalls — are in [docs/TECHNICAL.md](docs/TECHNICAL.md).

## Requirements

- Windows 10/11, 64-bit.
- Python 3.11+ for a source run (this release was verified with Python 3.14). PySide6 6.12.0 itself supports Python 3.10–3.15.
- The packaged build needs no Python installation.

## Setup from a fresh clone

```powershell
git clone https://github.com/pvndr/ClipNest.git
cd ClipNest

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`requirements.txt` holds runtime dependencies only. For tests, install the development set instead, which includes the runtime dependencies:

```powershell
python -m pip install -r requirements-dev.txt
```

If PowerShell blocks the activation script, skip it and call the interpreter directly, for example:

```powershell
.\.venv\Scripts\python.exe main.py
```

## Run from source

```powershell
python main.py
# or
python -m clipnest
```

## Tests

The suite runs headless through Qt's `offscreen` platform plugin, so no window is shown and no display is needed:

```powershell
python -m pytest
```

The local test suite contains 444 tests. They never touch the real clipboard, the production database, the registry or your DPAPI keys: a fake clipboard, temporary databases and an INI-backed preference store are injected everywhere, with guards that fail a test which reaches for the native APIs.

Two checks need the real machine rather than a fake and are deliberately outside the suite:

```powershell
# Real DPAPI + real SQLite: round trip, tamper refusal, migration, retention
.\.venv\Scripts\python.exe tools\verify_release.py

# Disposable databases for packaged-build checks (throwaway directories only)
.\.venv\Scripts\python.exe tools\seed_database.py legacy <dir>\clipnest.db
.\.venv\Scripts\python.exe tools\seed_database.py damage-canary <dir>\clipnest.db
```

The [GitHub Actions workflow](https://github.com/pvndr/ClipNest/actions) runs the test suite on a Windows runner for pushes and pull requests. The initial workflow run completed successfully. See the Actions page for individual step results and test counts.

## Build the Windows executable

ClipNest packages with PyInstaller into a **one-folder** application: Qt loads its platform, style and image-format plugins from disk, and keeping them visible turns a missing plugin into a diagnosable error instead of a silent startup failure inside a self-extracting archive.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean ClipNest.spec
```

A successful build exits `0` and produces:

```text
dist\ClipNest\ClipNest.exe        # The application (GUI subsystem, x64)
dist\ClipNest\_internal\          # Python, Qt DLLs, plugins, bundled artwork
```

The build bundles no database, preference file or user path; the packaged application creates its data under `%LOCALAPPDATA%` on first launch, exactly like a source run. There is no installer — copy the `dist\ClipNest` folder anywhere on a 64-bit Windows machine and start `ClipNest.exe`.

If the build stops with `PermissionError: [WinError 5] Access is denied` under `build\` or `dist\`, that directory carries the Windows `FILE_ATTRIBUTE_READONLY` flag (sync agents such as OneDrive set it). Clear it and build again:

```powershell
attrib -R /S /D build
attrib -R /S /D dist
```

## Downloads and checksums

There is **no published release yet**. When one is published, it will appear on the repository's [GitHub Releases page](https://github.com/pvndr/ClipNest/releases) as a ZIP archive of the one-folder Windows x64 build. The exact file name will be stated in the release notes.

Once a release exists, a SHA-256 checksum will be published alongside its ZIP, so you can verify the download before running it:

```powershell
Get-FileHash .\ClipNest-<version>-windows-x64.zip -Algorithm SHA256
# or
certutil -hashfile .\ClipNest-<version>-windows-x64.zip SHA256
```

Compare the printed value with the checksum in the release notes. Treat a mismatch as a failed download or a tampered archive and don't run it. Checksums are not yet published, so no published value exists to compare against today.

## Where ClipNest stores data

| Location | Contents |
|---|---|
| `%LOCALAPPDATA%\ClipNest\clipnest.db` | Encrypted clipboard history (SQLite) |
| `%LOCALAPPDATA%\ClipNest\clipnest.log` | Diagnostics; never clipboard content |
| `HKEY_CURRENT_USER\Software\ClipNest\ClipNest` | Preferences (`QSettings`) |

Nothing is written inside the source tree or next to the executable. Set `CLIPNEST_DATA_DIR` to an **absolute** path to keep the database, the log and an INI preference file inside one directory instead — useful for a portable copy and for validating a build without touching your own history. A relative value is ignored and logged.

**How DPAPI behaves across Windows profiles.** Snippets are encrypted with Windows DPAPI (`CryptProtectData`) using the key Windows holds for the current user account. There is no ClipNest password and no key file, so:

- The history can be read only by the same Windows account on the same machine profile. Copying `clipnest.db` to another account or a restored profile makes it unreadable — by design.
- Losing the profile means losing the history. There is no recovery key and no backup copy.
- When the history cannot be unlocked, ClipNest reports it and exits without replacing, recreating or deleting the file. The database stays byte-identical, so it can be read again after signing in with the right account.
- DPAPI protects the file from other users and from offline inspection, not from malware running as the same user, and an administrator who resets or takes over the account may be able to unlock it.

## Privacy and security limits

ClipNest is local-only: no account, no cloud sync, no analytics, no telemetry, and no clipboard content in any log, notification or error message.

- **Sensitive-data detection is a heuristic.** It recognises several families of secrets and refuses to store a match, but a password written as ordinary prose is still saved, and unrecognised formats get through. It is a filter, not a guarantee. See the rule table in [docs/TECHNICAL.md](docs/TECHNICAL.md).
- **Windows privacy markers are cooperative, not enforced.** They are read before any text is touched and applied fail-closed, but they are only as trustworthy as the application that set them, and ClipNest cannot know whether a copy made while it was not running was marked.
- **Deletion is best effort.** `PRAGMA secure_delete` plus a `VACUUM` remove snippets from the active database file; it is not forensic erasure. Copies can survive in backups, snapshots, filesystem free space, SSD wear-levelling or an earlier plaintext database.
- **Encryption is per Windows profile**, as described above.
- **Platform support is Windows x64 only.** The build was produced and checked on one Windows installation; other Windows versions and 32-bit or ARM hosts are not claimed.
- **No installer, no auto-start, no global hotkey.** Only the in-window shortcuts exist; a system-wide quick-search hotkey is deferred.

## Troubleshooting

Start with `clipnest.log` in the data directory above. It records what happened — capture skips, pause changes, tray problems, storage failures — and never records clipboard content.

| Symptom | Cause | What to do |
|---|---|---|
| *"ClipNest could not open its clipboard database"*, then the app exits | The history was encrypted by another Windows account, or its data was modified | Nothing was deleted. Sign in as the original account, restore that profile, or move `clipnest.db` aside to start a new history |
| No tray icon | Windows hides new notification-area icons in the overflow, or the artwork is missing | Enable the icon under *Settings > Personalization > Taskbar > Other system tray icons*; a missing asset is logged and leaves the window with close-to-quit |
| Copied text is not recorded | Monitoring is paused, the source set a privacy marker, the text matched a sensitive rule, it was whitespace-only, a duplicate, or longer than 10,000 characters (only the first 10,000 are kept) | The banner, the status bar and the log name the reason — never the content |
| The app starts paused without being asked | The saved pause state could not be read, so ClipNest started paused instead of guessing | Resume from the banner, the window button or the tray; the notification says why |
| A freshly built copy takes a few seconds on first start | Qt and the bundled Python are loading from cold storage | Later starts are fast; it is not hung |

## Uninstall

1. **Quit** ClipNest from the tray menu, then delete the folder you copied the build into.
2. Delete `%LOCALAPPDATA%\ClipNest` to remove the history and the log (SQLite may leave a `-journal` or `-wal` file beside the database, so delete the folder).
3. Delete the `HKEY_CURRENT_USER\Software\ClipNest` key to remove preferences.

Uninstalling removes the only copy: ClipNest keeps no backup, no cloud copy and no second database anywhere else.

## Project layout

```text
main.py                    # Thin entry point -> clipnest.app.main()
ClipNest.spec              # PyInstaller recipe (one folder, icon, version info)
build_support/             # Windows version resource for the executable
clipnest/                  # Application package (app.py is the composition root)
├── core/                  # Classifier, clipboard service, Win32 markers,
│                          # DPAPI protection, sensitive rules, SQLite storage
├── ui/                    # Window, tray, sidebar, cards, detail panel, settings,
│                          # theme tokens and inline SVG icons
└── assets/                # ClipNest.ico and its transparent PNG source
tests/                     # 444 headless tests, fakes and fixtures
tools/                     # Release verifier and disposable-database seeder
docs/TECHNICAL.md           # Implementation and privacy details
```

Module responsibilities and design rationale are documented in [docs/TECHNICAL.md](docs/TECHNICAL.md).

## Contributing

There is no contribution process yet, and no code of conduct. Issues and suggestions are welcome. Security problems should follow [SECURITY.md](SECURITY.md) instead of a public issue.

## License

**This project currently has no license.** No license file is included, and reuse, modification or redistribution permissions have not been granted through an open-source license. Under default copyright, all rights are reserved: the source is shared for viewing and evaluation, not for reuse. A license may be added later; until it is, don't assume any of MIT, Apache-2.0, GPL or any other terms apply.

Third-party components keep their own licenses: PySide6 and Qt (LGPLv3), PyInstaller (GPLv2 with a bootloader exception) and Python itself. The current one-folder build does not bundle their license texts, so anyone who redistributes a packaged build should add them alongside the executable.
