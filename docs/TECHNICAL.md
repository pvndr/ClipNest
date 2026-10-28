# ClipNest — technical notes

Implementation and privacy details for ClipNest `0.1.0`. The
[README](../README.md) covers installation, running, testing, packaging and the
user-facing behaviour; this document covers how it works and where the limits
are.

## Capture pipeline

`clipnest/core/clipboard.py` is the only module that reads the clipboard. It
listens to `QClipboard.dataChanged` (no polling) and runs every copy through the
same order of checks, so a refusal always happens before anything is stored:

1. Monitoring state (paused means no read at all).
2. Windows clipboard privacy markers.
3. Empty or whitespace-only text.
4. Sensitive-content rules (when enabled).
5. Consecutive-duplicate suppression, including the echo of a copy ClipNest
   itself performed.
6. Truncation to 10,000 characters, then a single encrypted insert.

Each refusal is announced without content ("Not saved: …") and nothing reaches
the database.

## Windows clipboard privacy markers

Source applications can mark clipboard content as private. Before reading any
text, ClipNest asks Windows for:

| Format | Meaning | ClipNest |
| --- | --- | --- |
| `ExcludeClipboardContentFromMonitorProcessing` | Presence-based exclusion | Never read, never saved |
| `CanIncludeInClipboardHistory` (`DWORD`) | `0` = keep out of history, `1` = allowed | `0` is never saved |
| `CanUploadToCloudClipboard` (`DWORD`) | Cloud-sync hint | Read for diagnostics only; ClipNest never uploads |

The markers are read through documented Win32 APIs (`user32`/`kernel32`) via
`ctypes` in `clipnest/core/clipboard_flags.py`, before the clipboard text is
touched. The decision is deliberately conservative:

- exclusion marker present, `CanIncludeInClipboardHistory == 0`, an unparsable
  history payload, or the clipboard being locked by another application all
  **skip** the capture;
- an absent marker is the only state treated as "no objection".

Limitations: this is best-effort cooperation, not enforcement. A source
application that sets no marker is captured; a marker is only as trustworthy as
the application that set it; and ClipNest cannot tell whether a copy that
happened while it was not running was marked. The marker read is synchronous, so
a clipboard held open by another process is treated as unreadable and the
capture is skipped.

## Sensitive-content detection

On by default, and switchable in **Settings → Privacy**. It refuses to store
content matching one of five conservative rule families in
`clipnest/core/sensitive.py`:

| Category | Recognises |
| --- | --- |
| `private_key` | PEM / OpenSSH `-----BEGIN … PRIVATE KEY-----` blocks |
| `api_key` | GitHub `ghp_`/`github_pat_`, OpenAI `sk-…`, Slack `xox?-`, AWS `AKIA…`, Google `AIza…`, GitLab `glpat-…`, JWT-shaped tokens |
| `credential` | `password`/`passwd`/`pwd`/`secret`/`token`/`api_key`/`client_secret`/`access_key` assignments with a secret-looking value |
| `one_time_code` | 4–8 digit codes next to `otp`, `one-time`, `2fa`, `verification`, `passcode`, or a 6+ digit code next to `code` |
| `card_number` | 13–19 digits that pass a Luhn check and a known issuer-prefix check |

The detector returns only the category, so a matched value can never appear in a
notification, a log record or an exception message. Environment references
(`${VAR}`, `%VAR%`, `os.environ[…]`) and template placeholders (`<your-key>`,
`{{ secret }}`, `********`) are treated as placeholders rather than secrets.

Limits of detection: it is a best-effort filter, not a guarantee. A password that
looks like ordinary prose (`My password is hunter2`) is stored; a hand-rolled
credential format is not recognised; only the first 20,000 characters of the
captured (already truncated) text are scanned. When a rule fires the capture is
skipped — ClipNest never stores a redacted fragment and never pauses monitoring
on its own.

## Deletion, expiry and retention

Deleting a snippet overwrites the freed pages instead of only unlisting them:
every database connection runs `PRAGMA secure_delete = ON`, and a user-requested
delete or **Clear history** is followed by a best-effort `VACUUM`. Automatic
trimming (the count limit and the age limit) never vacuums, so ordinary capturing
stays cheap. Compaction runs outside the delete transaction: if it fails, the
deletion still happened and the failure is logged (without content) rather than
surfaced as data loss.

The age limit is optional and stored as `history/retention_days`. It is applied
at startup, after every successful capture, and immediately when the setting
changes. Only unpinned rows are eligible; rows created exactly at the cutoff are
kept, a cutoff in the future is refused, and invalid values are rejected before
they reach SQL. Age expiry is independent of the count limit — both can apply.

None of this makes deletion forensically unrecoverable. `secure_delete`
overwrites the pages SQLite frees, but copies can survive in the filesystem's
free space, in SSD wear-levelling, in earlier database snapshots, in cloud backup
or in whatever tool reads the disk later.

## Monitoring state

The pause state is stored as `capture/paused` and applied in the
`ClipboardService` constructor, before `start()` connects to the clipboard, so
there is no interval in which a copy could be recorded while the window, banner,
tray label and tooltip all say "paused". Every control goes through the same
transition signal (the window button, the tray action, the banner's Resume and
the Settings page), and the window persists the value from that signal, so a
pause made from the tray is remembered too.

A stored pause value that exists but cannot be interpreted is not treated as
"off": ClipNest starts **paused** and says so once, because silently resuming
capture would override a privacy choice. An absent value means "running", which
is the default.

The first start that actually monitors explains once, in the notification bar,
that copied text is being saved locally and that Pause stops capture. The flag
(`notices/monitoring_shown`) is written when the notice appears. A start that
begins paused does not show it and does not set the flag.

## Encryption at rest

Since schema version 2 the `entries` table stores a `cipher` blob instead of
text. Every snippet is protected by `clipnest/core/protection.py` before it is
written and unprotected after it is read, using Windows DPAPI
(`CryptProtectData`/`CryptUnprotectData` through `ctypes`, with app-specific
entropy and no UI prompt). There is no ClipNest password and no key file: the key
is derived and held by Windows for the current account, and every blob carries an
integrity check, so a tampered row fails to decrypt instead of returning
corrupted text.

No dependency was added for this. DPAPI is part of Windows, `cryptography` is not
installed, and a hand-rolled cipher would have been worse than the platform's
authenticated encryption. `ProtectionError` messages contain no content.

Migration from a plaintext database is automatic and transactional:

1. `PRAGMA user_version` is `0`/`1` and the table has a `text` column, so the rows
   are read, protected one by one and written to a new table.
2. The old table is dropped, the new one is renamed, indexes are recreated and
   `PRAGMA user_version = 2` is set — all inside one `BEGIN IMMEDIATE`.
3. After the commit a `VACUUM` removes the plaintext pages from the file.

If any step fails (protector unavailable, disk error) the transaction rolls back:
the plaintext table stays exactly as it was, `user_version` is unchanged, and the
application reports the failure instead of starting with a half-written history.
There is deliberately **no plaintext backup file**.

Because ciphertext cannot be matched with `LIKE`, `search()` decrypts the stored
history in memory and filters there. That is bounded by the configured history
limit, so it scales with what is already on screen rather than with the file.

**Key recovery is an explicit decision, not a guess.** A `meta` row holds a
protected canary. If a later start cannot unlock it — a different Windows account
or machine, a restored profile, tampered data — ClipNest raises a `StorageError`
saying the history cannot be read, and does **not** replace, recreate or delete
the file. The recovery path is manual: sign in as the original account, restore
the original profile, or move the database file aside to start a new history.

In the packaged build that failure is a dialog titled **ClipNest** reading
*"ClipNest could not open its clipboard database"*, followed by exit code `1`;
the reason is also in `clipnest.log`. The file is left byte-identical, so moving
it back after signing in with the right account restores the history intact.

Limits worth knowing: DPAPI protects data from other users and from offline
inspection of the file, not from malware running as the same user, and an
administrator who resets or takes over the account may be able to unlock it.
Copies of a plaintext history made before the migration (backups, snapshots, file
history) remain plaintext, and no encryption can change that.

## Application icon asset

The window, taskbar and tray icon use the ClipNest artwork, which ships in the
repository:

```
clipnest/assets/clipnest.ico                     # primary (16/24/32/48/64/128/256 px)
clipnest/assets/clipnest_icon_transparent.png    # transparent source, used if needed
```

The ICO is loaded once and shared by `QApplication`, the main window and the tray
icon. If the ICO is missing or undecodable, `ui/app_icon.py` falls back to the
PNG; if neither can be loaded the app still runs: it logs the expected path,
starts without an icon, and **keeps close-to-quit**, because an icon-less tray
icon cannot be seen or right-clicked. No placeholder icon is invented. The PNG
has a fully transparent body, so the dark window and taskbar show through the
glyph; this is the artwork as delivered and is intentionally unchanged.

## Preferences reference

User preferences are stored with `QSettings` (`clipnest/preferences.py`), not in
the database:

```
HKEY_CURRENT_USER\Software\ClipNest\ClipNest
```

| Key | Values | Default |
| --- | --- | --- |
| `appearance/theme` | `dark`, `light` | `dark` |
| `history/limit` | whole number, 10–5,000 | `500` |
| `history/retention_days` | whole number, 1–3,650, or unset | unset (off) |
| `privacy/sensitive_detection` | `true`, `false` | `true` |
| `capture/paused` | `true`, `false` | `false` |
| `notices/monitoring_shown` | `true`, `false` | `false` |

When `CLIPNEST_DATA_DIR` is set to an absolute path, the same values live in
`settings.ini` inside that directory instead of the registry.

A missing or unusable stored value falls back to the default instead of raising,
so a hand-edited registry entry cannot stop the app from starting. Tests always
point `QSettings` at a temporary INI file, so the developer's own preferences are
never read or written.

## Global shortcut (deferred)

The planned `Ctrl+Shift+V` system-wide quick search is **not implemented**, and
nothing in the UI advertises it. PySide6 exposes no portable global-hotkey API,
so the only dependency-free route would be Win32 `RegisterHotKey` through
`ctypes` plus a `QAbstractNativeEventFilter`. That route fails silently when
another application already owns the combination, cannot be exercised by the
headless test suite, and needs a policy for the failure case. Rather than ship a
hotkey that sometimes does nothing, ClipNest keeps the in-window `Ctrl+K` and
`Esc` shortcuts only.

## Packaging

`ClipNest.spec` (checked in) decides the build: the entry point is the same
`main.py`, the artwork is bundled to `clipnest/assets`, the executable gets the
ClipNest icon and a version resource (`build_support/version_info.txt`), and the
console subsystem is switched off. `--onedir` is used on purpose — Qt loads its
platform, style and image-format plugins from disk, so keeping them visible makes
a missing plugin a diagnosable error instead of a silent startup failure inside a
self-extracting archive.

The build contains **no** database, preference file or user path. It also does not
bundle third-party license texts (Qt, PyInstaller, Python); a redistributed
package should include them.

### The `PermissionError: [WinError 5]` build failure

If the build stops with `PermissionError: [WinError 5] Access is denied` on a
directory under `build\` or `dist\`, that directory carries the Windows
`FILE_ATTRIBUTE_READONLY` flag. Windows refuses to remove a read-only directory,
so the previous build's cleanup (`--clean` purging `build\ClipNest`, and `COLLECT`
replacing `dist\ClipNest`) aborts before the build starts or before the artifact
is rewritten: the process exits `1` while an older `ClipNest.exe` is still on
disk, which is why the failure looks harmless. Sync and backup agents such as
OneDrive set that flag on directories they process, so this happens when the
checkout lives inside a synced folder. Clear the flag and build again:

```powershell
attrib -R /S /D build
attrib -R /S /D dist
```

## Project structure

```
main.py                     # thin entry point -> clipnest.app.main()
ClipNest.spec               # PyInstaller recipe (one folder, icon, version info)
build_support/
└── version_info.txt        # Windows version resource for the executable
tools/
├── verify_release.py       # real DPAPI + SQLite release checks
└── seed_database.py        # disposable legacy / damaged databases
clipnest/
├── __init__.py             # version metadata
├── __main__.py             # supports `python -m clipnest`
├── app.py                  # composition: repository + service + window + tray
├── paths.py                # data directory, database and log location
├── logging_setup.py        # rotating content-free log file
├── assets/                 # icon artwork (clipnest.ico + PNG source)
├── preferences.py          # QSettings: theme, limits, privacy switches
├── core/
│   ├── classifier.py       # text / link / code heuristic (pure Python)
│   ├── clipboard.py        # ClipboardService: dataChanged -> entries
│   ├── clipboard_flags.py  # Win32 privacy markers read before capture
│   ├── protection.py       # DPAPI at-rest protection + inert fallback
│   ├── sensitive.py        # best-effort secret detection (category only)
│   └── storage.py          # ClipboardRepository: parameterized SQLite
└── ui/
    ├── main_window.py      # layout, wiring, navigation, hide-to-tray
    ├── tray.py             # Show / Pause / Clear / Quit menu
    ├── app_icon.py         # icon asset lookup (never fabricates artwork)
    ├── sidebar.py          # category navigation (icon, selected, hover)
    ├── history_view.py     # scrollable stack: cards / state / skeleton
    ├── snippet_card.py     # one snippet card + relative time helper
    ├── detail_panel.py     # selected snippet preview and actions
    ├── state_panel.py      # empty, paused and error states
    ├── notification.py     # inline action banner (copy, pin, warnings)
    ├── dialogs.py          # clear-history confirmation
    ├── settings_page.py    # Appearance / History / Privacy / Shortcuts cards
    ├── icons.py            # inline SVG icons tinted per theme colour
    └── theme.py            # theme tokens, stylesheet, QPalette
tests/                      # 444 headless tests, fakes, fixtures, conftest.py
docs/TECHNICAL.md           # this document
```

## Why this layout

- `app.py` is the only composition root: it builds the repository and clipboard
  service, injects them into the window, then wires the tray (`create_tray_icon`
  + `wire_tray`). `main.py` stays a two-line shim.
- `ui/tray.py` is a thin emitter: each menu action raises a signal and `app.py`
  decides what it means. The window never imports the tray, so the two are tested
  separately.
- `ui/app_icon.py` owns the asset lookup and the "expected path" message; it never
  draws, downloads or substitutes artwork.
- Monitoring state has one owner, the clipboard service. The window button and the
  tray action both follow `paused_changed`, so they cannot drift apart.
- `core/storage.py` is the only module with SQL. `core/clipboard.py` is the only
  module that reads the clipboard. Both raise/report rather than silently
  swallowing failures, and neither logs clipboard content.
- `ui/main_window.py` composes the pieces, but each part of the interface is a
  small widget of its own. Widgets are presentation only: they receive
  `ClipboardEntry` values and emit user intent (copy, toggle pin, delete) as ids,
  so no database or clipboard logic lives inside a widget.
- `core/classifier.py` has no Qt or I/O dependency, so category filtering is
  plain, testable logic rather than widget tree inspection.
- `ui/theme.py` centralises every colour and style rule in one stylesheet plus a
  matching `QPalette`, so widget code stays free of inline styles.
- `paths.py` is the only module that decides where files live; `CLIPNEST_DATA_DIR`
  exists so a packaged build can be validated without touching real history.
- `logging_setup.py` writes diagnostics to one rotating file and never records
  clipboard content; `app.main()` configures it before anything can fail, which is
  why a packaged build can be diagnosed without a console.

## Implementation notes

- Dependencies are installed only into the project's `.venv`, which is
  git-ignored. `requirements.txt` is runtime only, `requirements-dev.txt` adds
  pytest, and `requirements-build.txt` holds PyInstaller, which is never imported
  by the application.
- The theme uses Qt's Fusion style as a base so the dark purple styling renders
  consistently regardless of the Windows accent colour setting. Dark is the
  default. `clipnest/ui/theme.py` also carries a complete `LIGHT` theme;
  **Settings → Appearance** swaps the app stylesheet and palette at runtime, and
  widgets that paint theme-coloured SVG icons re-render them because icon pixmaps
  are cached per colour. There is deliberately no system-theme detection.
- Icons are inline SVG strings rendered with `QSvgRenderer`, which ships with
  PySide6, so the UI added no dependency. The tray menu reuses the app stylesheet.
- The tray is optional at every level: no system tray, an icon that cannot be
  shown, or a missing icon asset all leave the window with its normal close-to-quit
  behaviour rather than hiding an app the user cannot reach.
- Truncation notices are tracked for the current session only: the stored row
  holds the clipped text and no extra column was added to the schema.
- Defaults live in `clipnest/app.py`: `HISTORY_LIMIT` (500) and
  `MAX_TEXT_LENGTH` (10,000). They are constructor arguments of the repository and
  the clipboard service, so tests can override them. The saved history limit from
  **Settings** overrides that default at startup; changing it later calls
  `ClipboardRepository.set_history_limit()`, which reuses the same retention query,
  so pinned rows are still immune.
- The database schema is version 2 (`PRAGMA user_version`), and the version is
  written inside the same transaction that creates or migrates the tables. A
  database from any earlier build is upgraded in place without a copy, and a
  failure leaves the original file untouched.
- The packaged executable is the same `main.py` entry point and the same code
  paths as a source run; packaging adds no behaviour, only bundling.
