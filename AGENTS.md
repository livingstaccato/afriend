# afriend

This repository ships a Python package (`afriend`) whose console
script is `afriend`, plus a skill/plugin payload that challenges specs, plans,
and reviews by dispatching them to other agent CLIs as independent adversarial
reviewers.

## Using the tool

Use `$afriend:review` for an explicit product review;
the five selectable skills are `afriend`, `review`, `status`, `configure`,
and `resolve`. Conversational `afriend review` and `afriend status` route to
focused skills and are not executable aliases: use `afriend run <artifact>`
for a review, `afriend status <run-id-or-path>` for a run, and `afriend doctor`
for readiness. Use `afriend init --guided` for a no-write setup preview and
`afriend profiles` for safe named profiles. All four modes -- `report`,
`crossexam`, `gate`, `loop` -- ship; see
`src/afriend/assets/entrypoints/review/references/modes.md`.
`afriend resume <run-id>` routes to `afriend run --resume <run-id>`, not to
claim resolution; it requires neither disposition nor evidence.

## Layout

- `src/afriend/` — the runtime package (stdlib-only, no runtime
  dependencies). `cli.py` is a thin entry point; the work lives in
  `cliargs.py`, `prompt.py`, `dispatch.py`, and `commands/`.
  Platform-specific process/filesystem primitives live behind a shared
  interface: `procgroup.py` (POSIX process groups) and `wingroup.py`
  (Windows Job Objects, via raw `ctypes` calls into `kernel32.dll` rather
  than `pywin32` — no new dependency); `filelock.py` wraps `fcntl.flock`
  (POSIX) vs. `msvcrt.locking` (Windows) behind one API; `secureio.py`
  branches internally between a POSIX `dir_fd`-chained walk and a
  Windows name-based walk with a **documented weaker** TOCTOU guarantee
  (Windows has no `dir_fd`/`fchmod` at all). `procio.py`'s pump threads
  are non-blocking + `selectors`-polled on POSIX and plain blocking reads
  on Windows (no `select()` on pipes there), relying on Job Object
  termination to unblock a stuck read/write the way group termination
  does on POSIX. `afriend runs prune` remains POSIX-only for now — its
  deletion machinery uses `dir_fd` directly, not through `secureio.py`.
- `src/afriend/assets/` — canonical package data: runtime
  `adapters/`, `harnesses/`, `lenses/`, plus five `entrypoints/` skills.
- `plugins/afriend/skills/` — the composite projection: focused
  skills map directly; router references and runtime data live below
  `skills/review/`. Never edit it directly; edit `assets/` and re-sync.
- `docs/` — prose docs and architecture diagrams. Excluded from `ruff format`
  so embedded code fences in historical specs/plans are left alone.

## Working on it

```bash
make install      # uv sync
make test         # pytest
make quality      # every portable CI gate, wheel checks, and tests
```

`make quality` runs every portable CI gate, including wheel construction and
isolated installation. Linux CI additionally installs bubblewrap and requires
the real OS-confinement tests to execute; macOS cannot reproduce that Linux-
specific assertion locally. Use `make act-ci` for the closest local Linux run.

Two gates are especially easy to trip:

- **`plugin-sync`** fails if the canonical entrypoint/runtime projection and
  the plugin differ. After editing `assets/`, run `make plugin-sync-copy`.
  It governs `plugins/afriend/skills/` only; the manifests are edited by hand.
- **`version-sync`** fails if `VERSION` disagrees with plugin metadata or an
  exact dependency/version in either compatibility distribution. Bump the
  canonical package, plugins, and both compatibility projects together.

Live evals are manual, because each makes real model calls on your own
logins: `make eval-claude` and `make eval-codex` check which skill a host
selects (`plugins/afriend/evals/README.md`), and `make eval-friends` checks
whether friends find the defects a past review found (`evals/friends/README.md`).
None is part of `make quality`; their scripts' tests run in `make test` with no
model call.

`mypy --strict` runs against `src/` only; `tests/` is deliberately exempt.
