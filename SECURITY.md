# Security policy

ClipNest stores clipboard history on the local machine and encrypts it with
Windows DPAPI. Security reports about the application, its data handling or its
packaged build are taken seriously.

## Supported versions

| Version | Status | Supported |
| --- | --- | --- |
| `0.1.x` | Release candidate, not yet published | Yes |
| anything older | Does not exist | No |

Only the current `0.1.x` line receives fixes. There are no long-term support
branches, and no update mechanism ships with the application: a fix arrives as a
new build that you replace by hand.

## Reporting a vulnerability

Please report security problems **privately**, not in a public issue, pull
request, discussion or comment.

There is no security email address and no private reporting channel configured
yet: the project has no GitHub repository or published release at this stage, so
GitHub's private vulnerability reporting and Security Advisories are not
available either. Until they are, contact the maintainer privately through a
platform-supported channel you already share (for example a direct message on
the platform where you obtained the project), and say that the message is a
security report.

Once the repository is published, use its **Security → Report a vulnerability**
form, which opens a private advisory draft.

### What to include

- The ClipNest version (from **About**, or the executable's file version).
- Your Windows version and architecture.
- What you expected, what happened, and the shortest steps that reproduce it.
- Relevant excerpts of `clipnest.log` **with any clipboard text removed** — the
  log itself contains no clipboard content, but surrounding lines pasted from a
  terminal may.

### Please do not include

- Clipboard contents, database files or a copy of `clipnest.db`.
- Credentials, tokens or private keys of any kind.
- Screenshots of a personal desktop or of your history list.

## Scope

In scope:

- The application source in this repository and its packaged Windows build.
- Clipboard capture policy (privacy markers, sensitive-content filter, pause
  state) and anything that would store content it should refuse.
- Encryption at rest and the handling of a history that cannot be unlocked.
- Logging and error messages that might disclose clipboard content or file
  paths beyond the documented data directory.
- The build and test tooling in this repository.

Known and documented limitations are not vulnerabilities on their own; see
[README → Privacy and security limits](README.md#privacy-and-security-limits)
and [docs/TECHNICAL.md](docs/TECHNICAL.md):

- Secret detection is a heuristic and will miss some secrets.
- Deletion is best effort, not forensic erasure.
- DPAPI protection is per Windows profile and does not defend against malware
  running as the same user.
- Windows clipboard privacy markers are cooperative, not enforced.

Out of scope:

- Attacks that already require code execution as the same Windows user, or
  administrator access to the account.
- Vulnerabilities in Python, Qt/PySide6, PyInstaller or Windows itself; report
  those upstream. If ClipNest's use of them makes the impact worse, that part is
  in scope.
- Anything requiring a modified build, patched binaries or a third-party
  redistribution.

## What to expect

Reports are handled on a best-effort basis by a single maintainer: an
acknowledgement, an assessment of impact, and — where a fix is warranted — a
patch in the next `0.1.x` build with credit if you want it. There is no bug
bounty, no guaranteed response time and no formal disclosure deadline; please
allow reasonable time for a fix before publishing details.
