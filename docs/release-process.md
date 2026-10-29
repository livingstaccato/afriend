# Release checks and recovery

Production tags must match `VERSION` and point to a commit on main. Before
building, the release workflow requires the latest push-to-main CI run for that
exact commit to have succeeded. All eight jobs and their required test/startup
steps must pass, including the full mutation probe on Python 3.13 and the named
Linux containment gate. Missing, pending, failed or skipped evidence blocks the
release. A tag created before CI finishes requires a workflow retry after green
CI. Annotated tags are resolved to their commit for this check.

Each PyPI publication job rechecks CI after its environment approval. Canonical
`afriend`, `adversarial-friends`, and `afriends` publish in that order as separate
jobs. The first two use the existing `pypi` environment, so approval may be
needed separately; `afriends` retains `pypi-afriends`. GitHub release creation
waits for all three. Publisher identities and environment protections must be
configured by the repository/package owner; local tests do not verify OIDC.

Retry failed jobs in the original workflow run while its verified distribution
artifact is available (seven-day retention). Before uploading, the helper reads
the package/version JSON API and compares every existing expected filename's
SHA256 to the original run artifact. Only missing files are staged. Identical
completed uploads require no further upload; mismatched hashes, unknown files,
malformed metadata and network errors stop recovery. A 404 denotes an unpublished
version. Do not rebuild a partially published version and assume its bytes will
match, or enable blind duplicate skipping. An expired artifact or mismatch needs
manual investigation rather than an automatic overwrite.

The manually dispatched TestPyPI workflow uses the same hash-checked recovery
with its own environments and original artifacts. It permits branch rehearsals;
it does not require push-to-main CI. Neither local quality nor loopback Twine
tests demonstrate actual TestPyPI/production publication or publisher policy.

Reviewer startup CI installs Claude, Codex, OpenCode and Pi at `latest` by
default. Optional repository variables `AF_STARTUP_CLAUDE_VERSION`,
`AF_STARTUP_CODEX_VERSION`, `AF_STARTUP_OPENCODE_VERSION` and
`AF_STARTUP_PI_VERSION` select versions explicitly. These checks exercise native
startup, canonical help and provider-specific invalid-value diagnostics without
model credentials. They do not establish authenticated review behavior.
