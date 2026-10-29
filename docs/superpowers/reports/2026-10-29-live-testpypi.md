# Live TestPyPI release verification

Recorded on 2026-10-29 UTC (2026-10-28 Pacific). The user requested completion
of the remaining live release checks. Production PyPI, merge and tags were not
changed.

## Publication and retry

[TestPyPI run 40801742187, attempt 1](https://github.com/livingstaccato/afriend/actions/runs/40801742187/attempts/1)
built and verified all six distributions from commit
`5234defbd35972094504b9191371f8acc9a9ffe6`, then successfully published
`afriend`, `adversarial-friends` and `afriends` version `0.13.0`. Each publisher
used GitHub OIDC and its existing TestPyPI environment; no API token, new login,
billing change or publisher configuration change was supplied by the host.
This proves the TestPyPI identities; production PyPI uses separate identities
and remains untested by publication.

[Attempt 2](https://github.com/livingstaccato/afriend/actions/runs/40801742187/attempts/2)
restarted the canonical publication job and its dependent alias jobs. All three
jobs succeeded: every hash-verification/preparation step passed and all three
upload steps were skipped because no files were missing. The retained build's
step timestamps stayed unchanged. This exercises completed-upload recovery with
original artifacts; interrupted upload cases were exercised separately by the
real Twine loopback tests.

The last alias's version JSON endpoint initially returned 404 after its upload
had succeeded; it subsequently exposed both files. Verification was withheld
until metadata was visible. Treat index propagation as a possible transient
retry failure, never as grounds for blindly skipping an existing file.

## Independent downloads and installation

All six files were fetched from TestPyPI's `test-files.pythonhosted.org` URLs.
Their complete bytes matched the original workflow artifact and their published
SHA256 digests. The preparation helper then returned `pending=false` for each
project. The durable [manifest](2026-10-29-testpypi-files.json) records these
hashes, rather than relying only on expiring workflow artifacts or local logs.

| File | SHA256 |
| --- | --- |
| afriend-0.13.0-py3-none-any.whl | `a92cabdec81474a10bed6904ef56583ba313faff2ebcd35e22e35322294967c3` |
| afriend-0.13.0.tar.gz | `709ac21ea0a905b696596711a378f08d4fc32f4989a8e2f2b50d57617a97f9ef` |
| adversarial_friends-0.13.0-py3-none-any.whl | `3f288259fa466df7fa998bec38fd9c09b8b67de84163c0e95ae624086de27303` |
| adversarial_friends-0.13.0.tar.gz | `4dcfb02da2ea19ee7b8f08f9854353419047b64bd9a9b3afb749a476e6a8920f` |
| afriends-0.13.0-py3-none-any.whl | `8b318c9a5d2cdc81189e09c044f4618618dee2eba6a4b10892d73d3596840046` |
| afriends-0.13.0.tar.gz | `db42c0309f5946d08a1c40127283ec3137caa00064025053881157e9d529aa9c` |

A new isolated environment installed all three projects at `0.13.0` from
`https://test.pypi.org/simple`. Outside the checkout, its console script reported
`afriend 0.13.0`. Installed metadata declared no canonical runtime dependencies;
both compatibility packages required exactly `afriend==0.13.0`.

This record applies to the named source commit and uploaded bytes. Later skill
or documentation changes are not represented as already published. A new
TestPyPI rehearsal of changed distribution bytes needs a new version, because
published files cannot be overwritten. Production version `0.13.0` remains
unpublished.
