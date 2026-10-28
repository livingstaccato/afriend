# Installation and plugin troubleshooting

`afriend` has two separate installation surfaces:

- `uv tool install afriend` installs the `afriend` command-line tool.
- A Claude Code marketplace installs the `review`, `status`, `configure`,
  and `resolve` skills.

The Python wheel contains the portable skill payload used by the command-line
tool. Claude Code marketplaces use the repository's `plugins/` projection, so
they need a durable Git checkout.

## Claude Code: “Marketplace file not found”

If Claude reports that `plugins/.claude-plugin/marketplace.json` is missing,
the configured directory is incomplete. This commonly happens when a
scratchpad or copied directory omits hidden files.

Remove the broken marketplace entry, then add the `plugins/` directory from a
full checkout:

```bash
claude plugin marketplace remove afriend

cd /where/you/keep/repos
git clone https://github.com/livingstaccato/afriend.git
claude plugin marketplace add "$PWD/afriend/plugins"
claude plugin install afriend@afriend
```

If the checkout already exists, refresh it and add its exact `plugins/`
directory instead:

```bash
git -C /path/to/afriend pull --ff-only
claude plugin marketplace add /path/to/afriend/plugins
```

Before adding it, this file must exist:

```bash
test -f /path/to/afriend/plugins/.claude-plugin/marketplace.json
```

Use a stable checkout rather than a scratchpad or temporary directory. After
updating that checkout later, run:

```bash
claude plugin marketplace update afriend
```

## Confirm the active installation

```bash
afriend --version
claude plugin marketplace list
claude plugin list
```

The marketplace listing should show a durable directory ending in
`/afriend/plugins`. The command-line version and the plugin version may be
updated independently.

## Windows notes

CI's four **Windows startup** jobs install the real Claude, Codex, OpenCode,
and Pi npm CLIs and execute them through afriend's resolver and process runner.
Each checks version startup, advertised canonical option names, help startup,
and a deliberately invalid enum value in the full canonical invocation, with
a required nonzero exit and diagnostic. Checking option names separately is
necessary because help and invalid enum values can short-circuit a CLI parser.
Missing binaries, crashes, timeouts, and empty diagnostics fail the job. These
are startup/argument checks with isolated credential-free profiles, not model
calls or authenticated review tests. AGY and Ollama are outside this matrix.

The default selector is `latest` on every run. Set repository Actions variables
`AF_STARTUP_CLAUDE_VERSION`, `AF_STARTUP_CODEX_VERSION`,
`AF_STARTUP_OPENCODE_VERSION`, or `AF_STARTUP_PI_VERSION` only when an explicit
version/range override is wanted. Remove an override to follow latest again.
Artifacts named `windows-startup-<provider>` record the requested selector,
installed npm versions, Node version, resolved executable, argv, stdout, stderr,
exit status, timing and cleanup results. Installs and failed probes also upload
their diagnostics; the startup jobs have no skip or continue-on-error path.

- **`codex`, `agy`, `opencode`, and `pi` need `--allow-unsandboxed-friend`.**
  Neither `bwrap` nor `sandbox-exec` exists on Windows. Once provider and
  external-tool policy permit a provider, `afriend doctor` can report it as
  `ready` while explaining that OS confinement is unavailable and a run
  without the flag will refuse it. This is the same fallback a Linux host
  without `bwrap` installed uses. External-tool denial is a separate check:
  `agy`, for example, remains `policy-blocked` without an explicit
  `--allow-external-tools=agy` grant. `claude` confines its own writes and
  needs no sandbox exception.
- **A `.cmd`/`.ps1`-shimmed CLI (a plain `npm install -g` install) is found
  and run correctly** — `afriend` resolves the binary via a CWD-safe
  wrapper around `shutil.which` (`execresolve.safe_which`) before spawning
  it rather than passing the bare name to `Popen`, which Windows'
  `CreateProcess` cannot resolve through `PATHEXT` on its own.
- **Weaker filesystem-race protection.** `secureio.py`'s POSIX path uses
  `dir_fd` to hold an open parent directory across every step of a write,
  so a symlink swapped in mid-operation can't redirect it. Windows has no
  `dir_fd` at all; the equivalent there re-validates each path component by
  name and refuses an existing symlink or NTFS junction/mount point, which
  narrows this race rather than closing it. Documented, not silent.
- **Run-owned artifacts have no Windows-native privacy control.** On POSIX,
  every run directory and file `secureio.py` creates is forced to `0700`/
  `0600`, unreadable by another local account. Windows has no equivalent
  mode bits, and — unlike the items above — this repository does not yet
  set an owner-only ACL there either: an attempt to do so via `icacls`
  during this port surfaced real permission errors on resume (the ACL
  interfered with a second process's own access to files it had itself
  created) that were not resolved in the time available, so it was backed
  out rather than shipped half-verified. A run's prompts (the whole
  document under review), raw model output, and claims are only as private
  as the parent directory's own inherited permissions — ordinarily just
  the operator's own profile, but explicitly weaker than the POSIX
  guarantee on a shared or multi-user Windows host. Track this as an open
  item rather than a settled trade-off; a correct fix needs more Windows
  ACL/token testing than this port could give it.
- **`afriend runs prune` is not yet supported on Windows** — its deletion
  machinery uses `dir_fd` operations directly. Every other command
  (`run`, `status`, `resolve`, `plan`, `runs list`) works normally.
