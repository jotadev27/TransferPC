# Security and privacy

## Local operation

TransferPC copies and verifies user-selected files on local or mounted
filesystems. It has no network client, listening server, telemetry, account
system, remote-control interface or automatic updater. It does not execute
transferred files. Refreshing locations only queries the operating system.
Mounted network filesystems, if selected, are handled by the operating system.

Publishing this repository does not expose a computer or authorize remote
access. Repository visitors can read the published code; they cannot run it
on the maintainer's machine. Installing or executing modified code is a
separate action. Changes proposed by other people require review before
merging or building a release. No review can guarantee that all future code,
dependencies or downloaded binaries are free of malware.

## Data boundaries

The application shows local file paths in its own window but does not save
transfer history or upload those paths. Temporary destination data is stored
in a private `.transferpc-*` staging directory and removed when the transfer
ends. A cleanup failure is reported. The app runs with the current user's
permissions and does not request elevated privileges.

Copy uses SHA-256 verification before and after publication. Move removes
sources only after verification and source validation. Existing destinations,
symbolic links and special source files are rejected. Cancellation preserves
sources before move cleanup begins. Once source removal begins, cancellation
does not interrupt that removal halfway through.

These checks protect normal transfers; they are not a sandbox against another
local process actively replacing directories during a transfer. Keep sources
unchanged and use destinations you trust. A failure after publication can
leave destination items; inspect both locations before retrying. Copying a
file does not disinfect it or determine whether its contents are malicious.

## Public repository and release contents

Only source, tests, packaging scripts, documentation and sanitized screenshots
belong in Git. `installer/`, build output, environments, caches, private
settings and local agent configuration are ignored. Build scripts use explicit
payload lists and normalize archive ownership so local usernames are not
included. Git commits use a generic project identity with a public no-reply
address rather than a personal name or email.

Before publishing, run `python3 packaging/audit_public.py` and review
`git status --short` and `git diff --cached`. The audit checks tracked blobs
throughout local history for the current home path, username and common
credential patterns. It is a useful check, not a replacement for review.
Release checksums detect changes relative to the published checksum file;
they do not prove authenticity if both files are replaced by an attacker.

## Reporting

Report non-sensitive bugs through the project's GitHub issues. Do not post
personal paths, credentials, private files or exploitable details publicly.
For a security issue, use GitHub's private vulnerability reporting if it has
been enabled by the repository owner. Otherwise request a private reporting
channel without disclosing the vulnerability itself.
