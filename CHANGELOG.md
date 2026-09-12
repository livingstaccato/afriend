# Changelog

## 0.11.0

Breaking: `run.json` is schema 5, the `afriend` router skill is gone, both
config files load through one pipeline, and `successful_friend_ids` records
every success rather than the independent ones only. A halted run written by
0.10.3 is refused by version rather than migrated.

**A thin roster silently became a narrow review, or a self-review.** The
review skill told the host to stop and offer choices when a judging roster
had one qualifying worker, and named none of the flags that perform them:
`--fresh-host-worker` appeared only in a further-reading reference,
`--enable-provider` and `--host-provider` nowhere at all. A reader who obeyed
the instruction still could not execute the option it told them to offer, so
the cheapest compliant path was to accept whatever `doctor` happened to
report ready. `doctor` made that worse by reporting `host-excluded` with
`reason=excluded because it is the detected host provider`, which reads as
terminal; it is a per-run default, reversible two ways, and the row says so
now. The rule also sat about a hundred lines below the sections explaining
how to run, so a top-down reader dispatched before reaching it -- it is now
in the preflight, above the dispatch block, with a table mapping each
reported readiness state to the flag that widens it. The skill also states,
in the second person, that the current harness never qualifies as an
independent friend under any flag, and that a review ending with the harness
as its only substantive reviewer is self-review and must be reported as one.

**Report escaping could be switched off by its own input.** `_escape_block`
escaped `<` with `re.sub(r"(?<!\\)<", ...)`; the lookbehind was there so an
already-escaped `\<` would not be doubled, but a lookbehind cannot count.
Two backslashes before a tag suppressed the escape as readily as one, and
CommonMark renders `\\` as a single literal backslash and then reads
`<div hidden>` as live HTML -- so any even-length backslash run in friend
prose reopened the unclosed-hidden-div defect that module's own docstring
records as having swallowed 3 of 3 findings. Brackets had the same hole at
one backslash. `&lt;` contains no backslash and cannot be defeated by any run
of them, which is why `_escape_cell` twenty lines away already used entities.
The escaping layer now lives in `reportescape.py`: it is the part of the
report with a security contract rather than a formatting one, and both
historical bypasses were in it.

**`afriend init` accepted exactly the flags that turn something off.** The
guided-only guard tested `not in (None, False, (), [])`, which is right for a
`store_true` and for a collection, and wrong for the two `store_const` pairs
whose off-switch carries `const=False` over a `None` default. It refused
`--enable-review-context` and accepted `--disable-review-context`, writing a
roster and exiting 0 with the request discarded.

**A resolution was verified against a baseline git never produced.** Three
faults, all in the direction of approving the fix. The gitignore guard was
named `_git_tracks` and returned `check-ignore`'s "is ignored" answer, the
inverse of its name and docstring; its one call site read it correctly, which
left the behaviour right and the contract backwards. Its `except OSError:
return False` reported "not ignored", which falls through to
`location-changed` and supports `fixed` -- the opposite of the refusal its
docstring promises. And `_git_show` returning None conflated "that path is
not in that tree" with "that tree is not here", so a garbage-collected
snapshot, or a run directory opened against a different clone, made every
existing tracked file report a change and approved a fix against no baseline
at all.

**One verbose friend destroyed a whole paid-for round.** `Ledger.append`
refusing an oversized record was correct, but it was called from a bare
per-claim loop with no handler, and the comment forty lines above that loop
already explains that halting mid-loop strands the claims of every friend
processed after. The UsageError escaped past `finish_run`, leaving no
run.json and no report.md, every other friend's answers unreported, and no
way to resume because restore needs run.json. A friend may print up to 32 MiB
against an 8 MiB ledger line cap, so this needed verbosity, not tampering.
One claim is dropped now, with a downgrade naming the friend and the reason.

**Six records asserted what the run never observed.** A recovered judge's
fallback audit row said `failed` while its verdicts were being counted from
the ledger. `--max-friends` discarded hand-written roster friends with
nothing anywhere to say which. `--lens was given` was written into durable
downgrades for operators who never typed it, because a review profile sets
the same attribute. A metadata size-bound handler wrapped `RunOutcome.apply`
and reported its validation failures as a size breach with a remedy that
cannot help. The review-context digest checked a second, unbounded read of
the artifact rather than the bytes about to be dispatched. And a non-string
`equals` in an adapter envelope rule was coerced to the empty string, which
matches no real event -- so the friend's answer was never recognised and the
run recorded it as having produced nothing.

**The diagram gate lost its own match to SIGPIPE.** `grep -q` exits the
instant it matches; under `set -o pipefail` the writer upstream takes SIGPIPE
and the pipeline reports 141, which an `if` reads as "no match". Both checks
in `verify_diagrams_render.sh` were written that way, so a render that IS a
PlantUML error image made the gate print "all 6 diagram sources render
cleanly" and exit 0. It only bites once the writer outruns the 64KiB pipe
buffer, and the largest SVG here is 64,010 bytes -- one detailed diagram away
from silently passing every broken render.

**The test suite read the developer's own afriend configuration.**
`rosterfile.discover()` reads `$XDG_CONFIG_HOME/afriend/roster.toml` and is
documented as trusted and picked up automatically; nothing isolated it, so
anyone who had ever run `afriend init` ran a different suite from everyone
else. Found when a bare `afriend init`, run while reproducing an unrelated
finding, created that file mid-session and the suite went from green to eight
failures across three files with no code change between the runs -- all of
them naming friends that appear nowhere in this repository. The direction
that matters is the inverse: the same leak can turn a real failure green.

**Which skill an activation eval selected is now asserted.** `claude plugin
eval`'s `tool_used` grader accepts only a tool name, so the positive cases
prove that *an* afriend skill fired, never which one, and a prompt that
wrongly routed `afriend resume <id>` to claim resolution scored the same as
the correct selection. `scripts/check_eval_skill_selection.py` reads the kept
transcripts and checks the qualified name against `expectations.json`, and
its rejection path is exercised against synthetic traces so it costs no model
call to verify. An empty directory returns 2 rather than 0 on purpose.

## 0.10.3

**A friend allowed through without a sandbox was handed a flag that
disabled its own.** `--sandbox danger-full-access` is codex's declared
`readonly_argv`, permitted by `check_denied_values` through a single
adapter-only exception whose whole justification is that afriend's outer
read-only OS policy binds the workdir instead. `allow_outer_readonly` was
computed from adapter declarations alone -- `sandbox_readonly_workdir and
sandbox_confine and not is_self_confining` -- and never from whether that
policy engaged, so on a host with no bwrap or sandbox-exec the exception was
granted on precisely the run where the policy never materializes. With
`--allow-unsandboxed-friend` the argv was `codex exec --json --sandbox
danger-full-access` with nothing outside it: the release recorded the lost
protection rather than not destroying it, and codex.toml's own stated
invariant -- the value "is refused when the outer mechanism is unavailable"
-- did not hold. The mechanism is probed before the argv is screened now,
and when it is absent `strip_outer_readonly_argv` drops the flag and its
denied value. Only that pair: agy's `readonly_argv` also carries `--agent
afriend-reviewer` and `--disable-slash-commands`, so suppressing the whole
list would have stripped the reviewer harness and re-enabled slash-command
expansion on exactly the run that already had no confinement -- a larger
authority than before the fix, and no longer the reviewer the report claims
it was. Nothing asserts what codex's own default sandbox does: dispatch
withdraws `readonly` from the capability either way, so the run records the
protection as lost rather than assuming a default holds.

**Readiness asked the real `shutil.which` while every other question went
through the injected one.** The confinement probe called `sandbox.detect()`
with no argument, so one row in `assess_all` was decided by whether the
machine running it happened to have bubblewrap rather than by the inputs it
was given -- and the existing test pinning codex's unqualified reason
therefore passed on macOS and in CI and failed on a contributor's Linux box.
`detect_confinement` is its own seam rather than a reuse of `which`, which
answers "is this ADAPTER's binary installed": every readiness test injects a
`which` naming a single adapter, so answering the confinement question with
it would report every mechanism absent on hosts that have one. The row also
predicted refusal with `needs_os_confinement` while dispatch refuses on `not
is_self_confining` -- two predicates for one statement, this release's own
defect in the row that reports it. An adapter with a working read-only mode
that opts into OS confinement anyway (the combination claude.toml's comment
weighs, and the loader permits) is not refused: it falls back to its own
flags and loses read protection only, and now says so.

**The friend that lost every protection read as the safer one.** report.md's
"Filesystem read scope" warning was gated on `write_protected and not
os_confined`. Once dispatch began withdrawing `readonly` for a skipped
sandbox, agy and codex under `--allow-unsandboxed-friend` reported
`write_protected: false` and dropped out of the warning entirely, while
claude -- write-protected and never confined -- stayed in it. Read exposure
is decided by confinement alone; write protection is irrelevant to what a
process may open, and the sentence no longer claims a property those friends
do not have. Separately, scope is chosen before dispatch and confinement is
decided per run, so `roster.py` and `cliargs.py` grant repo scope from
`is_readonly` -- true for agy only BECAUSE of its `[sandbox]` block. Moving
those three sites to `needs_os_confinement` would drop agy and codex to doc
scope on every host, including the ones where `readonly_workdir` genuinely
engages, so the mismatch is recorded as a downgrade where the run knows what
engaged rather than repaired by narrowing scope everywhere.

**A scalar in five more fields, and an empty string in two.** 0.10.2 routed
`readonly_argv` and the sandbox path lists through `_string_list` and left
`effort` and `env` unchecked, where a scalar reached `.items()`/`.get()` and
raised `AttributeError` out of `load_adapters` -- naming no file and
disabling every adapter in the directory, the exact defect shape that commit
fixed one field over. `base_argv`, `doc_argv`, `models_argv` and `env.pass`
were still shredded silently: `pass = "AWS_SECRET_ACCESS_KEY"` became 21
single-character names in the allowlist deciding what a confined child
inherits. The guard against a shredded path also stopped one bracket pair
short of the grant it exists to prevent: `_string_list` accepted `""`, which
resolves to the process working directory, so `[sandbox] write = [""]` --
what an unfinished placeholder looks like -- handed the invoking repository
over read-write while the record still reported `os_confined: true`. Refused
for path and name lists; still accepted for argv lists, where an empty
member is a legitimate flag value (agy's `base_argv` ends `"--print", ""`,
and that empty string is what satisfies `--print`).

**The guided roster described a sandbox the host did not have.**
`_render_roster` selected on the readiness state and read only
`assessed.model`, discarding the qualification the row carries, so on a
Linux box without bubblewrap `afriend init --guided --apply` wrote agy and
codex into the roster and told the operator each "runs under OS confinement
(§12.2)" -- a mechanism that is absent and a run dispatch will refuse. The
note it printed also called `repo` a limit ("limited to repo scope") while
`repo` is the WIDER of the two grants: a git worktree of the code under
review, against a doc-only directory. And the two-branch reason behind it
lived twice, in dispatch's refusal and inline in `init.py`, in two wordings
free to drift apart exactly as the four `is_readonly` copies did; it is one
`Adapter.confinement_reason` now, with a subject argument so dispatch's
message -- quoted verbatim in troubleshooting.md -- keeps its wording.

**Three of the five lines added for annotated tags could not run.**
`_git_text` allows only returncode 0, so `rev-parse --verify --quiet
'<sha>^{commit}'` either returned a commit id or raised git's own error: the
`UsageError("...must resolve to a commit")` written for a tag pointing at a
tree could never fire, and the re-run `cat-file -t` after it could only
confirm what `^{commit}` had already settled, at two extra subprocesses per
endpoint. Returncode 1 is allowed now so the rejection is reachable, the
identity guard stays on the peeled value that reaches the manifest, and the
second type lookup is gone. The outer non-commit check remains: an endpoint
that is DIRECTLY a tree or a blob never enters the tag branch at all.

**The signing fix was nine per-fixture copies in two spellings, and it
missed the trap one object type over.** `commit.gpgsign false` is set at
nine call sites across three modules while two other git-using modules set
nothing, so the release's one new test -- the only place in the suite that
creates an annotated tag -- inherited `tag.gpgsign` and would exit 128 with
"unable to sign the tag" for any contributor with global tag signing. An
autouse fixture in `tests/conftest.py` points `GIT_CONFIG_GLOBAL` and
`GIT_CONFIG_SYSTEM` at os.devnull, covering commit.gpgsign, tag.gpgsign,
gpg.format, core.hooksPath, commit.template and init.defaultBranch at once.
"One place" turned out to be two: `e2e_helpers._env()` builds a FIXED
environment dict and forwards only HOME, so roughly forty end-to-end git
invocations would have kept reading `~/.gitconfig` while the conftest
variable never reached them. Both are set, and the per-fixture lines stay.

**Two architecture diagrams could not be rendered at all.** `make diagrams`
failed on `run-flow.puml` and `gate-workflow.puml` with `Cannot find group`,
against every PlantUML from 1.2020.02 to 1.2026.0, with graphviz and UTF-8
both verified fine -- so the committed PNGs could not be reproduced from the
committed sources, and no CI job runs the target that would have said so. The
trigger is narrow: an activity carrying a `<<#COLOR>>` stereotype as the only
statement of a nested `if` that ends a `then` branch before its `else`. The
same colour written in PlantUML's canonical `#COLOR:label;` form parses
everywhere, so the fourteen coloured activities in those two files now use
it, and all six diagrams render. `run-flow` gained the branch this release
created: the mechanism is probed before the argv is screened, and where none
exists the weakening flag is dropped and the withdrawal recorded.

**Also.** The withdrawal added in 0.10.2 re-looked-up an adapter already
bound on every path reaching it and re-tested `spec.cli != "fake"`, which
the branch immediately after tested again and whose body performed the
identical `dataclasses.replace`; one guarded block computes both reasons
once. Adapter TOML validation moved to `adapterschema.py`, which is what the
777-line cap is for. The claim that removing the `--mode plan` docs pin left
the flag unasserted was withdrawn: `tests/test_confine_optin.py` and
`tests/test_adapters.py` already prohibit it, at token level, and a
re-addition fails three assertions across two files.

## 0.10.2

**A scalar where a list belongs granted a friend the whole filesystem.**
`readonly_argv`, `[sandbox] read` and `[sandbox] write` went straight into
`list()`/`tuple()` with no type check, unlike every sibling list field, so a
TOML string was accepted and shredded into its characters. For
`write = "~/.gemini"` -- brackets omitted, the same slip the format invites
everywhere else -- that yields the members `~` and `/`, which the policy
builder expanduser/resolves into $HOME and the filesystem root. The friend
got `--bind-try / /` on Linux and `(allow file-read* file-write* (subpath
"/"))` on macOS, read-write, while the run record reported it
`os_confined: true`. That is worse than no sandbox, because the record
certifies a confinement that does not exist. `readonly_argv = 0` had a
second shape: falsy, so it slipped past the declaration gate and then raised
`TypeError` out of `load_adapters` rather than a refusal naming the file --
and one bad file disables every adapter.

**Four places asked a different question from the one dispatch answers.**
Dispatch confines a friend when `not is_self_confining or sandbox_confine`;
the confinement notes, the guided roster, and the readiness path each asked
`is_readonly` instead. The two agreed until 0.10.1 gave agy a declared
read-only mode AND OS confinement, and then disagreed about exactly the one
adapter this release is about. agy was therefore absent from the note naming
whose filesystem is unconfined -- and because the mechanism is only probed
when that list is non-empty, a roster of agy alone never looked for a
sandbox at all. `init --guided` never mentioned that agy is sandboxed, and
the note it withheld would have said "no read-only mode" and "doc scope",
both false for agy. The refusal message said the same thing to the
operator's face. There is now one predicate, `needs_os_confinement`, and the
message states the reason it means.

**A skipped sandbox no longer reports the protection it did not provide.**
agy's `readonly = true` holds only while `sandbox.readonly_workdir` engages,
so a run with no mechanism available and `--allow-unsandboxed-friend`
recorded `write_protected: true` beside `os_confined: false`, and report.md
described the friend as write-protected but not OS-confined -- the audit
artifact asserting the one property the run had just lost. Dispatch already
withdrew readonly for unvalidated extra args; it now makes the same
withdrawal when the sandbox that was going to provide the protection never
ran. Readiness gained the matching admission: `afriend doctor` printed agy
ready and exited 0 on hosts where every agy run was refused, so an upgrade
from 0.10.0 turned a working friend into a per-run refusal with the
documented readiness check still green. The row stays ready -- the
executable is there, and the override still runs it -- and now says the
sandbox it needs is missing.

**Four tests and four comments still described the release they document.**
`test_only_adapters_without_a_readonly_mode_are_confined` derived the
confined set from `not readonly_argv` and asserted `{"opencode"}`, which is
still that predicate's answer, so the one test named for which adapters are
confined stayed green while naming a policy the code had stopped
implementing. The self-confining fixture in `test_confinement_record.py`
silently stopped being self-confining when declaration-by-argv was removed,
and its assertion went on passing only because a detected sandbox meant no
note was due either way. A docs test pinned `--mode plan`, which the adapter
deliberately no longer emits, requiring README and troubleshooting.md to
keep asserting it -- a drift detector holding drift in place. The
`readonly`/`self_confines` field comment still promised the inference this
project deleted, which is the belief that shipped agy unconfined. Deleting
`tests/test_plugin_command_alias.py` in 0.10.1 also took the only
success-path coverage of `copy_expected`, the destructive half of
`make plugin-sync-copy`; both assertions are back, retargeted at the
`.claude-plugin/` manifest that now lives beside it.

**`--range v0.10.0..HEAD` was refused for every annotated tag.** The review
context resolved a range endpoint and then required its object type to be
`commit`. An annotated tag resolves to its own tag object, so the error --
"range endpoint must resolve to a commit" -- named the one thing the tag
does resolve to once peeled. It is peeled now. Separately, every fixture
that builds a git repository set `user.name` and `user.email` but left
`commit.gpgsign` inherited, so a contributor with global commit signing and
a path-scoped signing key had 33 tests error at setup with exit 128.

## 0.10.1

**agy ran unconfined on flags that restricted nothing.** An adapter counted
as read-only and self-confining whenever it declared any `readonly_argv`, so
the presence of flags stood in for evidence that they worked. Measured
against installed agy 1.1.22, with the reviewer agent staged exactly as
dispatch stages it, none of the four restricted anything: the friend wrote a
file (relocated into `~/.gemini/antigravity-cli/scratch` by `--sandbox`
rather than refused) and read an absolute path outside its working
directory, with `tools: []` in the agent ignored. It was the one shipped
adapter running under no OS confinement and no restriction of its own. agy
is confined now, the way codex is, with `~/.gemini` granted read and write so
its token refresh still works -- withholding that is what risks provoking a
re-authentication. `--mode plan` is gone from its argv, having printed
`--mode plan has no effect` on every run since `--disable-slash-commands`
joined the same list.

**An adapter must say whether its flags work, not merely that it has some.**
`readonly` and `self_confines` are no longer derived from `readonly_argv`
being non-empty, and an adapter that declares restriction flags without
declaring both is now refused at load. The old inference could not
distinguish agy's four inert flags from claude's `--tools Read,Grep,Glob`
allowlist, which was measured and does hold -- asked to create a file, claude
answers `NO_WRITE_TOOL` and creates nothing. Both adapters now record what
was measured against the installed CLI, including claude's read gap, which
stays open deliberately: its credentials live in the macOS Keychain, and the
`~/Library/Keychains` grant that OS confinement would need hands a friend
every credential the operator has.

**Removed `/areview`.** It shipped in 0.10.0 as a shortcut for the review
skill, on the belief that a plugin's `commands/` directory yields a bare
slash command. It does not: plugin commands are namespaced by plugin, so it
was only ever reachable as `/afriend:areview` -- no shorter than the
`$afriend:review` it was meant to abbreviate, and a second surface with the
same behaviour is a thing that can drift.

## 0.10.0

**Security.** `claims.jsonl` was the one input a resume trusted, and it was
the input that decided whether work happens: a judge is handed only the
claims with no durable verdict, so anyone able to write into a halted run
directory could append forged verdicts for every contested claim and that
judge was never dispatched -- with the forgeries carried into the report as
votes a friend had cast. A durable verdict may now suppress dispatch only if
the judge's own version-2 batch records a vote on that claim; that batch
binds the judge, the round, the prompt bytes and the parsed capture by
digest. This costs no legitimate recovery, because the batch is persisted
before the first ledger append, and the crash window that does exist (batch
written, appends interrupted) is unaffected. Present since before 0.9.0.

**Prompts arrive on stdin.** Every shipped adapter now hands its prompt to
the CLI over stdin rather than argv, closing the last transports where a long
prompt could hit a single-argument size cap or leak into a process listing.
agy needed a JSON message per line, so adapters gained `stdin_template` --
validated at load, because a template that never names the placeholder would
send a well-formed message containing no artifact and record a review that
reviewed nothing.

**An exhausted quota is not a broken credential.** Auth failures abort a run;
a spent allowance now stops one friend, records a downgrade, and reports what
else that provider offers (`afriend providers models`). A failed friend's
audit row records what the CLI said failed rather than what it printed on the
way there -- codex on a spent quota wrote its reason to stdout and left only
a banner on stderr, so the row said `exit 1 (stderr: Reading prompt from
stdin...)` and the sentence naming the reset date was readable only in the
raw capture.

**One ready provider can reach a judging run.** Discovery built one friend
per provider, so a machine with a single ready provider could not satisfy any
judging policy -- including `distinct-sessions`, which exists to accept two
sessions of one provider. Discovery now fans a sole worker across further
lenses under that policy, and the refusal names the flag rather than leaving
it to be discovered. A quorum drawn from one provider is recorded as a
downgrade: those sessions share an account, a model and a failure mode.

**`/areview`** is a slash-command alias for the `afriend:review` skill.

Also fixed: a stream that emitted anything after its terminal event hid that
event and cost the full `--print-timeout` (7-12 minutes per hung friend);
model listings ran with the parent's whole environment and an inherited
stdin, bypassing the `env.pass` filtering every dispatched friend goes
through; quota downgrades were reported once per round rather than once; and
`make quality` now runs a mutation probe that can actually fail.

## 0.9.0

Every legacy compatibility path is gone. Each one was a second definition of
what a run, a configuration or a snapshot is, and the older definition was
completed with silent defaults -- which is where the defects were, because a
check satisfied by an absent field is not a check.

**Breaking.** A `run.json` or `session.json` written before 0.9.0 is refused
rather than upgraded. A run directory is plain text, so `report.md`,
`claims.jsonl` and the round transcripts stay readable without the CLI; a
session configuration can be replaced by deleting it or rerunning `afriend
setup`, which the refusal says.

Three of the removed paths were reachable from an edited `run.json` and are
fixed rather than merely deleted around:

- Judging resume derived host roles from a frozen `detected_host` and
  carried the saved authority state forward, so an advisory host could reach
  a verdict. The refusal that protects this no longer treats a known host as
  an exemption: the roles are derivable, but the authority state saved
  beside them was computed under a host-role model this version cannot
  confirm.
- `applied_response.request_sha256` binds a saved response to the request it
  answers. It was optional for a checkpoint already in `response-applied`,
  and the comparison defaulted the missing key to the value it was being
  checked against, so a response with no binding compared equal. It is
  required now.
- `successful_friend_ids` decides the participation floor and was derived
  from the friend audit rows only when absent -- so a `run.json` carrying the
  field was believed about which friends succeeded, including about one its
  own audit row records as `failed`. It is required and cross-checked
  against those rows.

Also removed:

- Run metadata migration. `run.json` matches schema 4 or is refused.
- The flat `repo_root`/`snapshot_sha` snapshot mirror and the tree walk that
  recovered a binding from a saved invocation path. The nested `snapshot` is
  the only identity, and bindings are resolved once at snapshot creation.
- `RESPONSE.json.applying`. Nothing wrote that pathname, but resume read it
  and could select it as the response source.
- Session configuration schemas 1 and 2, which loaded with review context
  silently off.
- The `legacy-unknown` sentinel. Where it marked something merely
  unrecorded, the report now says `unrecorded` or `role unknown`; where a
  resumed run's `external_tool_policy` was copied forward verbatim, the
  audit summary is now always the policy actually in force.

## 0.8.1

Fixes for evidence that did not survive being written down, and for an
artifact size limit that silently excluded one provider.

- Records the qualification policy a pre-0.8.0 run was actually admitted
  under, rather than letting resume fill the gap with the current default. A
  halted same-provider judging run created before 0.8.0 refused to resume,
  because it was re-admitted under `cross-provider` -- a rule that did not
  exist when it was accepted. Only the policy is recorded, never a verdict:
  host role is assigned at resume from the current environment, so a verdict
  computed during migration counts the advisory host as a worker.
- Replays a run's frozen qualification on resume instead of re-deciding it,
  so acceptance is a property of the run rather than of the binary reading
  it. The payload is still validated as hostile input, and a replayed
  verdict is still enforced: a run whose metadata says it never qualified
  does not become judgeable by being resumed.
- Stops stamping a literal schema version over terminal run metadata. Every
  completed run recorded schema 2 regardless of the schema that produced it,
  so a later migration would treat a new run as legacy.
- Reads the `claude` prompt from stdin. As one argv element it hit Linux's
  ~128KB single-argument cap, so any artifact past that failed to dispatch
  with E2BIG while codex handled the same artifact in the same run (#4).

## 0.8.0

A judging run now states the rule that makes its evidence independent, and
enforces it before dispatch instead of implying it afterwards.

- Adds qualification policies for judging modes. `cross-provider` (two fresh
  workers from different provider families) is the default; a run or review
  profile may select `distinct-sessions` (two fresh workers) or
  `distinct-models` (two fresh workers with different exact requested model
  identities). An unmet policy is refused before a run directory exists, and
  the selected policy is frozen into the run so a resume cannot be
  retroactively qualified by a later preference change.
- **Behavior change:** judging modes previously admitted any two independent
  friends regardless of provider. Two same-provider workers now need an
  explicit `--qualification-policy`.
- States what each policy did not verify. `distinct-sessions` checks only that
  invocations were separate, so the report says provider family and model were
  not compared rather than letting the policy name imply more.
- Refuses selection labels such as `fast`, `default`, and `unknown` as model
  identities under `distinct-models`; an accepted identifier remains a recorded
  provider request, not proof of the backend model that answered.
- Keeps an explicitly requested fresh worker on the host's own provider family
  in the roster. It stays independent and is disclosed as sharing the host's
  family, which is what lets a Claude-hosted task qualify beside Codex.
- Carries a next action on each worker completion event, so a host consuming
  the stream is told what a finished worker means for it rather than inferring
  that from the single run-level event at the end.
- Isolates the test suite from the developer's own environment and runs it in
  parallel.

## 0.7.2

Run evidence is easier to retain, inspect, and turn into an explicitly
reviewed follow-up without exposing raw friend transcripts.

- Adds `afriend runs list` and confirmation-gated `afriend runs prune` for
  retained terminal runs. Retention remains the default; pruning previews
  candidates unless `--confirm` is supplied and refuses unsafe, active, or
  malformed runs.
- Adds transcript-safe status triage that follows final claim lineage,
  preserves recorded resolutions, and links only report, ledger, and parsed
  evidence artifacts.
- Adds `afriend plan RUN`, which writes one durable, claim-linked `PLAN.md`
  proposal for unresolved terminal-run claims without dispatching friends,
  editing repository code, or changing review state.
- Makes the host/worker boundary explicit in the shipped skills: a completed
  worker reports its outcome and next action instead of becoming an implied
  queue, while host authority remains separate from provider tool grants.

## 0.7.1

Model selection is visible and auditable before a review begins.

- Shows each resolved friend's requested model and selection source before
  dispatch, so the selected review configuration is visible before any provider
  starts.
- Describes provider defaults truthfully: an omitted model is the provider CLI
  default rather than a verified backend identity, including OpenCode's generic
  CLI default.
- Persists requested models and their selection sources in both `run.json` and
  the report's friend table, preserving audit provenance after the run.
- Adds installation and troubleshooting guidance to the shipped Claude
  marketplace documentation, including provider readiness and model-selection
  diagnostics.

## 0.7.0

Context-aware review composition makes a review, plan, and related repository
changes available to friends as one explicit, frozen artifact.

- Adds configurable session review-context policy and `afriend context show`,
  `set`, and `compose` commands. Hosts can automatically combine unambiguous
  current-task inputs, ask when intent is ambiguous, and present the selected
  review intent and sources before dispatch.
- Binds plans, code reviews, and one or more repository changes
  deterministically, including untracked changes, into a size-bounded composite
  with a signed-content manifest. Friends receive the frozen composite rather
  than mutable source inputs.
- Preserves replay integrity: run metadata records the context provenance and
  resume refuses missing, forged, malformed, or mismatched context bindings.
- Updates the shipped skills, README, routing diagram, and architecture guide
  for context-aware review selection and preflight behavior.

## 0.6.2

A repository-review access correction for confined Codex friends.

- Allows only Codex's measured `~/.agents/skills` startup dependency as a
  read-only sandbox path; user configuration stays ignored, and apps and
  plugins plus built-in browser, computer, and web-search features stay
  disabled.
- Uses the outer read-only OS policy for Codex's review directory because its
  macOS command sandbox cannot nest inside that policy. Codex is refused when
  the outer policy is unavailable; this does not grant it a writable review
  checkout.
- Classifies a declared raw sandbox access diagnostic as **not assessed —
  judge access failure**. Affected claims remain incomplete and gate-blocking;
  they cannot become discarded merely because the judge could not read the
  review context.
- Aligns the current skill guidance and claim-state/gate diagrams with that
  contract.

## 0.6.1

`afriend` is the canonical project identity on GitHub and PyPI.

- Canonical repository: `livingstaccato/afriend`.
- Canonical distribution, Python import, command, and Codex/Claude plugin:
  `afriend`.
- `adversarial-friends` and `afriends` are metadata-only PyPI distributions
  that install exactly the matching `afriend` release. They provide no extra
  import, command, runtime code, or plugin payload.
- The release workflow builds, inspects, isolated-installs, and publishes all
  three distributions in canonical-first order.

## 0.6.0

The package and product were renamed to `afriend`. This source tag was not
published to PyPI because the new canonical project was not yet configured for
trusted publishing.

### Clean package identity

- Published distribution: `afriend`.
- Python import and source package: `afriend` in `src/afriend/`.
- Console command, Codex plugin, Claude plugin, skills, configuration, and
  runtime state: `afriend`.
- Removed the old Python package identity rather than shipping a compatibility
  alias; this is a deliberate clean cutover before external package adoption.

### Release assurance

- Updated wheel checks, isolated-install smoke tests, release artifact names,
  current documentation, and architecture diagrams for the new package.
- The successor release moves first-party repository URLs and image asset names
  to the canonical identity.

## 0.5.1

A compatibility hotfix for the Python versions Adversarial Friends declares
and a release gate that prevents an interpreter-specific broken wheel from
being published.

### Python compatibility and release gating

- Fixed immutable profile and session-config defaults so the installed CLI
  starts on Python 3.11 as well as Python 3.12 and 3.13.
- The release build now installs and starts the exact wheel on every supported
  Python version before it may publish to PyPI.

## 0.5.0

A repository-scope release that lets an artifact be reviewed against an
explicitly selected Git worktree without weakening frozen-input or replay
guarantees.

### Explicit repository review context

- Added `afriend run ARTIFACT --repo PATH`. `PATH` must name exactly a local
  Git worktree root; the artifact is independently frozen while friends receive
  the selected repository snapshot. `--repo` cannot be combined with
  `--resume`.
- Preserved automatic scope for artifacts whose resolved final target is inside
  their invocation repository. A repository-local symlink that resolves
  outside it is document scope only and does not create a repository snapshot.

### Replay integrity and release assurance

- Records automatic versus explicit scope in the original lifecycle event and
  rejects a resumed run if its saved metadata does not agree. Old runs that
  predate this field and lifecycle events continue to resume normally.
- Hardened snapshot binding, loop history, event parsing, and symlink-race
  behavior; synchronized the shipped skills, plugin projection, troubleshooting
  guidance, and architecture diagram with these contracts.

## 0.4.1

A reliability release that makes Linux-confined friends retain host resolver
configuration and makes incomplete reviews explicit instead of silently
appearing clean.

### Linux confinement and DNS

- Resolves the host resolver configuration and read-only binds its actual
  target into Linux `bwrap` confinement, covering systemd-resolved,
  resolvconf, and NetworkManager layouts.
- Adds regression coverage for those resolver layouts, including a real Linux
  `bwrap` runtime check.

### Incomplete-review reporting and safety clarity

- Reports an explicit, sanitized `0/N friends answered` outcome in reports,
  status, and terminal output; `--failure-summary report-only` keeps that
  outcome in the saved report while suppressing the terminal line.
- Preserves terminal failure precedence and tolerates malformed historical
  friend rows during status reconstruction.
- Clarifies that `--allow-unsandboxed-friend` is a fallback only when no OS
  confinement mechanism is available; it never disables available confinement
  and does not imply read protection.

## 0.4.0

An interaction-focused release that makes Adversarial Friends easier to set
up, observe, and steer without weakening the independent-review or
deny-by-default authority boundaries.

### Guided review sessions

- Added safe built-in review profiles (`quick`, `balanced`, and `thorough`),
  configurable session defaults, and constrained named profiles that cannot
  select providers, rosters, models, processes, or authority.
- Added `afriend init --guided` for a no-write setup preview and explicit
  `--apply` for precisely selected configuration changes. Guided setup keeps
  external tools denied and preserves normal roster overwrite protection.
- Records selected profile provenance while keeping saved run settings
  authoritative on resume.

### Run visibility and resolution

- Added private, append-only lifecycle events with safe correlation data,
  terminal completion feedback, and event-backed `afriend status` with a
  read-only watch mode.
- Added `afriend resolve --list` and `--next` for read-only claim discovery.
  Discovery preserves the existing evidence and disposition requirements for
  actual resolutions.
- Hardened live/resumed/legacy status reconstruction, untrusted event and
  ledger parsing, terminal rendering, and suggested command quoting.

### Product surface and assurance

- Updated the five shipped skill entry points, plugin projection, routing
  diagram, documentation, and activation evaluations for the current guided
  workflow.
- Added regression coverage for atomic guided setup, event privacy and
  terminal durability, read-only inspection, profile validation, and bounded
  discovery. The repository quality gate now verifies 2,102 tests.

## 0.3.1

A confinement and review-scope correction release.

- Preserved DNS for Linux `bwrap`-confined friends by read-only binding a safe
  resolved `/etc/resolv.conf` target when the host uses a symlinked resolver
  configuration.
- Made a doc-scoped run explicit before dispatch: an artifact outside a Git
  repository emits one stderr warning that friends can inspect only the
  artifact, not repository code.
- Updated the live documentation, architecture diagrams, and troubleshooting
  guidance for the scope and resolver contracts. Antigravity is named as the
  product while retaining `agy` where the CLI identifier is required.

## 0.3.0

An authority-focused release that makes Adversarial Friends easier to invoke
deliberately, clearer about the Codex host's dual role, and extensible to
provider harnesses without weakening deny-by-default behavior.

### Activation and host roles

- Narrowed conversational activation to `afriend ...`, `afriend to ...`, the
  full Adversarial Friends name, or direct skill selection; ordinary review
  requests no longer select the skill implicitly.
- Included Codex as an advisory host self-review by default in Codex, with
  `--exclude-self` as the opt-out. Host review remains non-independent and
  cannot satisfy judging admission, quorum, gate clearance, or convergence.

### Provider authority and harnesses

- Replaced the global external-tool escape hatch with repeatable,
  provider-scoped `--allow-external-tools=PROVIDER` grants while preserving an
  explicit `=*` global form and exact grant re-assertion on resume.
- Added generic, digest-pinned workspace-asset staging for adapter-controlled
  harnesses. Antigravity receives a constrained reviewer agent as defense in
  depth but remains policy-blocked unless explicitly granted for the run.
- Passed the Google provider's actual `GOOGLE_GENERATIVE_AI_API_KEY` variable
  to confined OpenCode friends alongside the compatibility variable reported
  by `opencode auth list`.

### Release assurance

- Hardened host-role, readiness, resume, workspace-asset, and report
  invariants; synchronized the packaged skill and Codex/Claude plugin payloads.
- Refreshed live documentation and architecture diagrams, with reproducible
  renders and complete distribution/install verification.

## 0.2.1

A contract-first hardening release that makes provider selection, authority,
and replay behavior explicit and fail-closed. It also completes the
end-to-end dogfood and release-quality work for the hardened runner.

### Provider policy and authority

- Added persistent provider enable/disable preferences and per-run overrides,
  with the current host provider excluded from automatic discovery unless
  `--include-self` is passed.
- Added readiness states and model configuration, so unavailable, disabled,
  host-excluded, unconfigured, and policy-blocked providers do not consume the
  friend cap.
- Denied provider-managed tools, plugins, apps, and MCP servers by default.
  Providers that cannot prove denial now fail closed unless the operator grants
  `--allow-external-tools` for that invocation.

### Replay and judging correctness

- Bound resume to its frozen artifact, repository commit, tree, blob, and
  invocation-local authority grants, rejecting changed or unverifiable input.
- Made `crossexam`, `gate`, and `loop` require two independent ready friends
  before creating a run; single-friend `report` remains available as an
  explicit downgrade.
- Centralized terminal outcomes and made unconverged loop exhaustion a ceiling
  with exit 11. Hardened checkpoint, ledger, merge, and judging recovery across
  crash and resume boundaries.
- Fixed an exact-call-budget resume regression where a completed report could
  not consume its already-written orchestrator merge response.

### Release assurance

- Raised the enforced source-file ceiling to 777 lines and expanded the
  contract, replay, authority, readiness, recovery, and end-to-end test suites.
- Added hermetic Ollama HTTP end-to-end coverage, wheel and source-distribution
  validation, isolated installed-CLI smoke tests, and Linux confinement checks.

## 0.2.0

A staged hardening release centered on replay-safe state, bounded
cancellation, durable evidence, and reports that state their actual security
guarantees. The durable ledger is now the single source used to reconstruct
claims, provenance, verdicts, resolutions, gate decisions, and reports.

### Correctness and replay

- Fixed transitive origin loss after resumed alias chains, so every friend
  that contributed to a canonical claim remains excluded from judging it.
- Made resolution verification independent of the invocation directory by
  anchoring evidence paths to recorded run context and resolving symlinked
  repository roots safely. `fixed` now requires verifiably changed evidence;
  unverifiable evidence can only support `rejected` or `accepted-risk`.
- Added early validation for all positive run ceilings and global model
  values, before artifacts or run directories are created or friends are
  dispatched.
- Added `ReviewState`, a deterministic ledger reducer with incremental/replay
  equivalence checks, transition validation, compatibility warnings, and
  generated sequence tests. Live runs, resumes, halts, gate decisions, and
  reports now derive their observable state through this boundary.

### Safety and durability

- Made HTTP cancellation bounded by moving each blocking request into a
  helper process that is terminated and, if needed, killed on abort.
- Made ledger appends POSIX-durable with complete-write loops, file `fsync`,
  parent-directory `fsync` on creation, and file-and-line corruption errors.
- Separated write protection, declared scope, transport, and actual OS
  confinement in `run.json` and report friend tables. Reports now warn when a
  write-protected executable still has same-user filesystem read access.

### Verdict semantics and release engineering

- Kept conflicting amendments contested instead of choosing one rewrite
  arbitrarily; every proposed amendment remains visible in the report.
- Included evidence assessment, counter-evidence, and amendment content in
  consecutive-round discard equivalence, while ignoring reasoning and
  confidence changes that do not change the substantive verdict set.
- Narrowed supported-platform metadata to macOS and Linux. `make quality` now
  includes wheel asset inspection and isolated installed-entry-point smoke
  tests; Linux CI remains responsible for the real bubblewrap assertion.

## 0.1.8

Three fixes, all found by cross-examining the runner's own `--resume` and
failure-handling machinery for the first time. The most serious: a friend
that could not authenticate used to discard the *whole round* it happened in
-- including findings from other friends that had already answered -- and
left no `run.json` or `report.md` behind at all. The other eight share one
cause: state that lives only in the process a `--resume` starts fresh
(`Budget.calls`, the repeat-failure tracker, merged aliases, a crash
mid-application) was silently lost or corrupted across a halt. A third gap,
unrelated to resume: a run where 1 of 50 friends answered used to exit `0`,
identically to 50 of 50 -- `--require-friends N` closes it.

### An auth failure lost the whole round it happened in, not just that friend

`dispatch_round` raised the moment ANY friend in a round classified as a
deterministic auth failure (§14/§7.2) -- before its caller had a chance to
persist a single result. A round with four friends, two of which produced
real findings before the third hit a lapsed login, lost all four: the
exception propagated straight out of `run_critique`/`run_rounds`, so
`persist_result` never ran for anyone in that round, and `cmd_run`'s only
local `except` catches `NeedsOrchestrator`, not a plain `AfError` -- so it
reached `cli.py`'s top-level handler, which prints a message and exits.
`run.json` and `report.md` were never written at all. Reported independently
against a real run: an opencode auth failure discarded findings from two
friends that had already answered.

The raise inside the recording loop had a second effect nothing had
noticed: it also skipped `RepeatTracker.record` for every friend later in
iteration order than the one that tripped it, so their outcomes were never
recorded either.

`dispatch_round` now returns `(results, auth_abort_message)` instead of
raising. `run_critique` and `run_rounds` persist and merge every result
exactly as they would for a normal round, then surface the abort
themselves: `CritiqueOutcome`/`CrossexamOutcome` gained an `auth_abort`
field, `cmd_run` stops scheduling further rounds and iterations once it
sees one, and `decide_exit` gained an `auth_abort` parameter that forces
exit `1` ahead of every other outcome -- including a partial `any_success`,
since a broken roster has not produced the review its exit code would
otherwise claim. `run.json` and `report.md` are now written with whatever
the run actually produced before the abort, the same as any other stop.

### A crash mid-resume could permanently strand a run

`commands/resume.py`, cross-examined for the first time -- inevitable, given
today's changes to it were the highest-density source of defects this
project has found in itself. All eight findings are closed. Two (c-0004,
c-0008) were a regression in this afternoon's own fix; the other six share a
different root cause -- in-memory state that a `--resume` (always a new
process) never inherits -- and are fixed below it.

**The regression.** `_mark_response_consumed` protects a resume against
replaying a response that was already FULLY applied. It did not protect
against a crash *between* writing a ledger record and renaming the file --
the exact case that motivated it in the first place, just narrower. For
extraction, a crash after finding 1 of 3 landed re-appended finding 1 on
retry, under a fresh id: permanent duplicate content. For merge, worse:
`canonical_claims` had already folded away the `duplicate` id a prior
partial application removed, so the retry's own validation refused the
now-unknown id with `UsageError` -- and every subsequent retry re-read the
identical file and hit the identical refusal. A transient crash became a run
that could never be resumed again.

Fixed by reading progress from the ledger itself, the same source
`canonical_claims` and the claim counter already read, rather than a new
progress file: how many `lens="extracted"` claims already carry this round
number, and which `duplicate` ids already have an Alias recorded for it.
Extraction skips the leading N entries a fresh read of RESPONSE.json
provides; `read_response` gained a `tolerate_duplicates` parameter so it
skips re-validating exactly the merges a prior attempt already finished,
instead of refusing the whole file. Verified against the actual crash: each
new test writes the ledger records a real kill -9 between an append and a
rename would leave behind, then calls the retry path directly.

**The other six: state a resumed process never inherited.** `Budget.calls`
and `RepeatTracker`'s disabled-friend set are in-memory dataclasses, and
`--resume` is a new process -- so a `--mode loop --merge orchestrator` run
halting once per iteration forgot its own spend and its own repeat-failure
history at every halt (c-0001, c-0007, c-0002). A 5-iteration loop could
blow past `--max-calls` by a large multiple with the ceiling never firing,
each resuming process believing only its own round 1 had ever run; a friend
disabled for repeated failure in iteration 1 came back after every resume.
Both are now persisted into `run.json` at every halt (`spent_calls`,
`repeat_tracker`) and restored on resume -- the true cumulative total, not
the one-round guess `resume_round_one` charged back before.

`resume_round_one` also never passed `final_block` to `run_rounds`, so a
resumed judging call always took the default `True` even mid-loop -- an
amendment nobody could judge in the last round of a non-final block was
marked `incomplete` with a downgrade telling the operator to raise
`--max-rounds`, even when the very next iteration was about to judge it
(c-0005). And a halt's own report had forgotten what an EARLIER iteration,
in a process that has since exited, had already produced: `all_aliases` was
a process-local accumulator that restarts at `[]` on every resume, so a
second halt's "Merged duplicates" section silently dropped the first
iteration's merges (c-0003); `write_halt`'s own `render()` call never passed
`states=`/`verdicts=` at all, so a halt mid-loop showed raw findings with
none of the reasoning an earlier iteration's judges had already produced,
even though `carry_over` held it directly (c-0006). Aliases are now read
straight from the ledger (`merge.ledger_aliases`) rather than accumulated,
the same fix pattern as everything else in this batch: state that must
survive a halt lives in the ledger or in `run.json`, never only in a
variable.

`commands/haltstate.py` now holds everything a halt persists and a resume
restores, split out of `resume.py` (which crossed the then-current line cap for the
third time today) and `commands/run.py` gained a `finish_run` helper in
`runmeta.py` for the same reason.

### `--require-friends N`: c-0013, closed

The last open finding from cross-examining `commands/run.py`. A run where 1
of 50 friends produced a usable answer exited `0` -- identically to a run
where 50 of 50 did. The report already said plainly that a single answer is
one opinion rather than disagreement between several; nothing in the exit
code carried that, so a CI wrapper reading only the exit code could not tell
the two apart and read a near-total roster failure as success.

Opt-in and unenforced by default (exit `12` when set and missed): a fresh
checkout with one CLI installed is a normal use of this tool, not a degraded
one, and a floor nobody asked for would fail that case for no reason. Outranks
gate and crossexam completeness in the exit precedence -- a run below the
declared floor has not produced the review its exit code would otherwise
claim -- but a ceiling still outranks it, since a truncated run has not
evaluated anything including quorum. Unenforced, not guessed at, on a
`--resume` of `--merge orchestrator`: that path never dispatches a fresh
critique round in the resuming process, so there is nothing of this run's own
to count, and reporting a failure on a number the process never saw would be
worse than not checking.

## 0.1.7

A documentation release. Every shipped doc was read against the code it
describes -- `README.md`, `AGENTS.md`, `SKILL.md`, all three `references/`
pages, and the `docs/` index -- and ten claims were found to be false. Three
of them told a reader that a feature which ships does not exist, which is the
worst thing a doc can do: it does not merely fail to help, it actively stops
someone using what they already installed.

Nothing about the runner changed. If you are on 0.1.6, the code you have is
the code this describes.

### Docs that described a build from several releases ago

- **`AGENTS.md` said `report` was "the only mode this build implements".**
  `crossexam`, `gate` and `loop` have all shipped since 0.1.0. This is the
  file an agent reads first when working in the repository.
- **`ledger.md` said `verdict` records were "schema only -- not produced by
  this build"**, three paragraphs after its own opening line says all four
  record types are written. Every judging mode has written verdicts since
  `crossexam` landed. The section now documents the record as it is actually
  written -- `confidence`, `counter_evidence` and `amended_claim` included,
  none of which were mentioned -- with an example taken from the real dataclass
  rather than from memory, and the correct `evidence_assessment` values
  (`confirmed`/`disputed`/`unverifiable`, not the `verified` a reader could
  reasonably have inferred).
- **`ledger.md` said an `orchestrator` alias "has no implementation to produce
  it yet".** `--merge orchestrator` ships, and that alias is the only way two
  differently-worded claims are ever linked -- which the same page's closing
  paragraph flatly denied was possible at all.

### Exit codes, in three places, none of them agreeing

- **The README's table listed five codes and omitted `10` and `11`** -- while
  the prose two sections above it told you to expect exit `10` from `--merge
  orchestrator`. A CI wrapper written from that table treats a halt for merge
  adjudication as an unknown failure.
- **`SKILL.md` listed `--mode gate` and `--mode loop` as *causes* of exit
  `2`,** a usage error. Both are supported modes. It also omitted `10`
  entirely and carried a doubled word.
- **`modes.md` claimed `--preset` set to anything but `inherit` was a usage
  error,** in a table three sections below the one documenting what
  `thorough` and `cheap` do. Replaced with the usage errors that are real: a
  `--resume` naming a run that never halted, and an `--out` directory that
  already exists.

### Numbers and output nobody had re-checked

- **The README advertised 365 tests, twice.** The suite collects 912.
- **The `doctor` sample output had the wrong rows in the wrong order** with
  column widths that never matched the format string. It is now literal
  captured output.
- **`--pass-env` and `--no-progress` appeared in no document at all.** Both
  are now in `modes.md`, along with `--include-self`, which only ever appeared
  parenthetically inside an exit-code description.
- **The README still said a run "prints one thing".** Since 0.1.6 it also
  prints per-friend progress and a heartbeat to stderr -- the change that
  exists specifically so a long run is not mistaken for a hung one, described
  nowhere a user would look for it.
- **`docs/architecture/README.md` listed three of the five diagrams**;
  `crossexam-states` and `gate-workflow` had been rendered, committed, and
  linked from two other pages without ever being added to the index that
  claims to enumerate them.
- The run-directory listing in both the README and `SKILL.md` omitted
  `<friend>.sandbox`, the file that records what a confined friend was
  actually allowed to read.

### Two gates, so this is the last time

The existing guard scanned shipped docs for absence claims and checked them
against `--help`. Every defect above slipped past it, because it only knew
how to recognise a **flag**: nothing in "the only mode this build implements"
or "not produced by this build" is a flag.

- `test_no_shipped_doc_calls_a_shipped_mode_unimplemented` checks any
  paragraph claiming absence against the modes in `IMPLEMENTED_MODES` and the
  record types in the ledger, and covers `AGENTS.md` and `docs/README.md`,
  which the flag guard never read.
- `test_the_advertised_test_count_is_the_real_one` takes the count from
  collection rather than from a constant someone has to remember to update, so
  the only way to change the advertised number is to change the suite.

### Also

`v0.1.6` was published to PyPI and never tagged in git -- the mirror image of
0.1.4, which was tagged and never uploaded. Both leave the same question
unanswerable: which commit is the version you installed. The `v0.1.6` tag is
added here, at the commit that was uploaded.

`ci/verify_wheel_assets.sh` opened with `rm -rf dist`. Harmless on a CI
runner with nothing in it; destructive when a release is cut by hand, where
it sits between `uv build` and `twine upload dist/*` and quietly deletes the
sdist. 0.1.7 reached PyPI as a wheel with no source distribution, the only
release of this project missing one, and the sdist was uploaded separately
once that was noticed. The check now builds into a scratch directory.

## 0.1.6

Everything here came out of pointing the tool at its own source twice more --
`commands/run.py` and the leftover deadlock from `dispatch.py` -- plus the
first time it was ever run against a different project.

**Two things a user notices immediately.**

A run is no longer silent. A crossexam took tens of minutes and printed
nothing until it was over, which is indistinguishable from a hang; there is
now a line per friend and a heartbeat naming whatever is still outstanding.
And `SKILL.md` states the runtime, so an agent invoking this skill no longer
reads a normal twenty-minute wait as a failure.

**One that matters if you use `--merge orchestrator`.** That mode combined
with `--mode loop` was effectively broken: claim ids were re-issued after a
merge, the resumed judging round inherited nothing from earlier iterations,
the loop could not converge, and a second `--resume` could apply the same
adjudication twice. All four are fixed.

**Still open, deliberately.** `c-0013`: a run where one friend out of fifty
succeeds exits `0`. The report is honest about it -- it says plainly that a
single answer is one opinion rather than cross-examination -- but the exit
code does not carry that, so CI reads success. Changing it is a change to the
exit-code contract, not a bug fix, and is left for a decision rather than
made quietly.

### commands/run.py, cross-examined

Thirteen claims against the largest module never examined, twelve upheld and
one deadlocked. Twelve are fixed here. They fell into three groups.

**Resume and loop, five claims and one cause.** `--mode loop --merge
orchestrator` halts once per iteration, and almost nothing survived the halt.

- **A merged claim's id was handed out twice.** The resumed counter was
  `len(all_claims)`, and that list is the CANONICAL one, which drops claims a
  merge retired. Merge `c-0002@1` into `c-0001@1` and the next iteration
  minted `c-0002@1` again -- into an append-only ledger, where aliases,
  verdicts, states and resolutions all key on that id. The counter now comes
  from the whole ledger (`merge.next_claim_number`): an id is spent when it is
  written, not while it happens to still be live.
- **The resumed judging round inherited nothing.** `resume_round_one` called
  `run_rounds` with no `prior`, so a loop resumed at iteration 2 re-seeded
  every claim `contested` and re-judged what iteration 1 had settled, at full
  fan-out, with judges shown none of the prior arguments. The same call was
  also missing `tracker`, `keep`, `extra_args` and `pass_env` -- one omission,
  five behaviours.
- **A resumed loop could not converge.** The streak arithmetic on that path
  was `next_streak(streak, failed=False, dry=round_is_dry(False, True))`, and
  `round_is_dry(False, True)` is always False -- so it zeroed the streak
  `loop_position` had just restored, every time. Termination needs two
  consecutive dry rounds, so the run went to `--max-loop-iterations` paying a
  full fan-out per iteration after it had stopped learning anything.
  `write_halt` now records what the halted round actually did.
- **An adjudication response could be applied twice.** `ledger.append` is a
  bare JSONL write with no dedupe, and nothing marked `RESPONSE.json` used, so
  a second `--resume` re-appended every extracted claim under fresh ids. This
  was the deadlocked claim, and the deadlock was the useful part: two judges
  amended it to say the defect is real but on the extraction branch rather
  than the merge branch the claim named, and the third refuted it precisely
  because amending would invalidate the stated scenario. The merge branch is
  genuinely guarded. The response is now renamed `.applied` -- kept, not
  deleted, because it is the operator's own written judgment.

**A fix applied to one of two paths.** The wall-clock cap reserved
`KILL_GRACE_S` and floored at one second for judging rounds and did neither
for critique rounds, so a critique friend dispatched with 20s left got a real
kill deadline of 80s, and with 0.6s left got a timeout of `0` -- which agy
turns into `--print-timeout 0s` and dies instantly, having spent a call and
marked the run incomplete. Two friends raised this independently from two
lenses, which is what an asymmetric fix looks like from outside. The helper
now lives in `ceilings.within_deadline` and both paths call it.

**Durability and hygiene.**

- `run.json` and `report.md` are written to a sibling temporary file and
  renamed. `write_text` truncates first and writes second, so a crash between
  the two left the file existing and invalid -- and `--resume` reads run.json
  to reconstruct the run, so that was permanent loss of an hour of metered CLI
  time. A `loop` rewrites it every iteration, so the window recurred.
- A deliberate stop no longer waits out every other friend. `pool.map` raises
  as soon as one worker does, but `ThreadPoolExecutor.__exit__` then joined
  the rest -- so a flag-validation error raised in the first second surfaced
  only after seven other friends had each spent up to `--timeout`.
- `AF_CLOCK_OFFSET_S` is validated and recorded. It was a bare `float()` on an
  environment variable, so a malformed value was a traceback; and because it
  shortens every wall-clock ceiling, an ambient value in CI made a run report
  `budget-exhausted` while the downgrade blamed a `--max-wall-clock` the
  operator had set correctly.
- Three comments describing code that is not there, including one asserting a
  lock ordering both branches above it violate.

- The startup ceiling warning counted one iteration. `--mode loop
  --max-loop-iterations 5 --max-rounds 3 --max-calls 12` with four friends
  computed 12 and said nothing, then hit `budget-exhausted` mid-run -- the
  exact outcome the warning exists to pre-empt. `derive_max_calls` had always
  multiplied by iterations, so the default and the warning disagreed about
  what the same run costs.

One claim is not fixed, and is recorded rather than hidden. **c-0013** -- one
friend succeeding out of fifty exits `0`, so CI reads success and discards the
rest -- is a change to the exit-code contract rather than a bug fix, and is
left for a decision.

`cmd_run` crossed the then-current line cap twice more along the way, so
`commands/setup.py` now holds everything decided before the first dispatch.

### A friend's scratch no longer lands in the tree it is reviewing

`c-0009`, the one claim from the `dispatch.py` cross-examination that
deadlocked. Judges split on what "scratch inside the isolation directory"
meant, and neither ran it. It means the git worktree: for a repo-scope
friend the working directory IS the snapshot of the code under review, so
pointing `$TMPDIR` and the `$XDG_*` variables at it made the runner dirty
the tree it had just taken a snapshot to keep pristine. A friend running
`git status` to orient itself saw two untracked directories that were not in
the commit it was reviewing, and the CLI's own config sat among the files it
had been asked to critique.

Scratch now goes to a sibling — `<friend>.private` beside `<friend>` under
the round's isolation root — granted to the sandbox as that one directory.
Not the parent: the parent is the isolation root, which holds every other
friend's worktree, and granting it would repeat the `$TMPDIR` mistake one
level down. Torn down with the isolation root, so it needs no cleanup of its
own.

The fix is in the caller. `private_dirs` was never wrong — it wrote under
whatever root it was handed, and `_dispatch` handed it `cwd`. The choice is
now a named function, `childenv.private_root_for`, because nothing named it
before and so nothing could test it. `tests/test_scratch_placement.py` pins
it at both levels, and three of its cases run a real sandboxed process:
the friend can still write to its redirected `$TMPDIR`, the reviewed
worktree is left byte-for-byte as it was found, and a write aimed at a
neighbouring friend's tree is refused.

### The spec's §12.2 divergence said the gap was still open

It recorded that closing confinement "needs verified credential-path
declarations for `claude`, `codex` and `agy`, which this project does not
have". codex's were captured and verified by running it confined in 0.1.5;
codex opts in through `[sandbox] os_confine`, and the doc-scope hole closed
when `readonly_argv` started being emitted in both scopes. Three statements
about the code had stopped being true. The residual gap is now stated as
what it is: `claude` and `agy`, each with the reason it is still out.

The guard that exists to catch exactly this — a doc calling an implemented
feature absent — had a blind spot the shape of a text wrap. It scanned
single lines, and every doc here is hard-wrapped prose, so "not in this
build" and the flag it disclaims routinely land on different lines. It was
strictest on the one formatting these docs never use. Now scans paragraphs,
verified against the wrapped case it previously let through.

## 0.1.5

**The first release published since 0.1.3, and 0.1.3 is what PyPI still
serves.** 0.1.4 was tagged and never uploaded, so anyone who installed this
tool from PyPI is running a version with both confinement holes 0.1.4 fixed:
`codex`, `claude` and `agy` inheriting every exported secret, and a binary in
`~/bin` granting read over the whole home directory. Upgrading is the point of
this release.

On top of 0.1.4, this adds what came out of pointing the tool at its own
source five more times — `normalize.py`, `spawn.py`, `procio.py`,
`crossexam.py` and `dispatch.py` — and closing the last of the recorded gaps.
One more security fix among them: `--unsafe-extra-args "--sandbox
danger-full-access"` bypassed the denied-value screen, because the argv that
was checked was not the argv that ran.

### spawn.py, cross-examined

Eleven claims upheld against the module that runs a friend, six of them about
code written an hour earlier. Eight are fixed here; the ninth is a limitation
rather than a defect and is recorded below.

- **Truncated output reached the extraction path after all.** spawn's
  docstring says a killed friend's truncated output "never enters the repair
  path". That was true of `normalize()` and only of it: `commands/critique.py`
  hands raw stdout to §14.2 extraction gated on `payload is None`, which is
  exactly what a timed-out or overflowed result carries. Extraction is the
  path built to pull meaning out of text nothing else could parse, so it is
  the worst possible destination for a cut-off buffer.
- **A noisy stderr discarded a good answer.** One `overflow_event` was shared
  by both pumps, so a friend that answered correctly on stdout and merely
  chattered on stderr had its valid answer thrown away unparsed. Nothing reads
  stderr for content; its truncation cannot make an answer wrong. Now recorded
  as an annotation while the answer still goes through `normalize()`.
- **Overflow stopped draining rather than stopping accumulation.** The first
  version returned from the pump at the ceiling, leaving the pipe unread — so
  the friend blocked writing and died flushing at exit, and a complete valid
  answer came back as `exit 120`. It now reads and discards, which bounds
  memory just as well and leaves the child able to exit on its own terms.
- **The early-answer probe joined the whole buffer for adapters that could
  never use it.** `answer_is_complete` rejects every ndjson envelope
  unconditionally, while the cheap guard added to avoid that join is *true* on
  almost every poll, since each NDJSON line ends with `}`. The envelope kind
  now settles it once, before the loop.
- **A pump ignored its stop signal while data kept arriving.** The loop
  `continue`d straight past the check after any successful read, so a writer
  trickling bytes kept it from ever running — the thread then lived until the
  byte ceiling stopped it, a bound but not the documented one. Checked every
  iteration now, with a drain window so setting the event still never
  truncates what is already buffered.
- **The stdin pump could block forever.** The output pumps were built
  non-blocking because a descendant can inherit a friend's stdio and hold it
  open; `_pump_stdin` used a plain `write()`, which blocks once the pipe fills
  and nothing drains it. Prompts carry the whole artifact, so "larger than the
  pipe buffer" is ordinary. Now non-blocking on the same selector pattern.
- **Repair amplified a bounded capture into an unbounded cost.** The byte
  ceiling bounded what was captured, not what normalizing it cost:
  `drop_trailing_commas` allocated one list entry per character, measuring 61
  seconds and 308MiB of peak memory on a 32MiB input — per friend, several in
  flight. It now scans between the only characters that can change its state,
  collects the spans it intends to drop before building anything, and returns
  the original string untouched when there are none. The same input takes
  0.005s and no measurable extra memory.
- **`output_truncated` was recorded where nobody could read it.** Its stated
  purpose is to let a reader tell truncation from a friend that said little;
  it was written to the result and to no file, unlike every sibling flag.

Not fixed, and stated rather than implied: a descendant that calls its own
`os.setsid()` leaves the process group and cannot be reaped or reliably
detected. Closing that needs a cgroup, PID namespace or job object, none of
which macOS offers an equivalent of. It remains covered by
`test_setsid_escapee_is_not_reaped` and by the orphan reporting that infers it
from a pipe held open.

spawn.py crossed the then-current line cap again, so the pumps moved to `procio.py`.

### dispatch.py, cross-examined

Eleven claims, eight upheld. Two of them I had already found reading the file
while the run was in flight; the friends reached both independently.

- **The HTTP transport ignored the abort signal entirely.** The exec
  transport has honoured it since signal handling was added — a cancelled run
  must not leave a friend running, nor make the operator wait out a timeout
  they already interrupted. `run_request` never received the event, so Ctrl-C
  on a run with an ollama friend sat until the network deadline expired. The
  request runs on a worker now and the wait ends on abort.
- **The argv that was screened was not the argv that ran.**
  `check_denied_values` fires before `--unsafe-extra-args` are appended.
  `parse_unsafe_extra_args` refuses a denied *flag* on those tokens but never
  looked at denied *values*, so the flag spelling of "turn the sandbox off"
  was blocked while the value spelling —
  `--unsafe-extra-args "--sandbox danger-full-access"` — went straight
  through to the CLI. The final argv is re-screened.
- **The wall-clock ceiling was a ceiling only for friends that behaved.**
  Dispatch hands `run_process` a kill deadline of `spec.timeout +
  KILL_GRACE_S`, a full extra minute, which the cap ignored: a hung friend
  overshot the operator's limit by that minute plus the group escalation
  windows. The cap reserves the grace, and when only the grace would fit
  nothing is dispatched — an existing test asserted the older half-guarantee
  (cap the timeout, ignore the kill) and was updated to the stronger one.
- **The round most likely to trip the argv size limit was the one not
  measured.** `PROMPT_ARGV_WARN_BYTES` was documented as covering every
  friend prompt and only ever ran in the critique round. Judging prompts are
  strictly larger — the same artifact plus the claims under review plus prior
  verdicts. The check is shared now.
- **The stderr sanitizer left attacker-controlled links clickable.** It
  stripped `` ` * _ [ ] < > `` and claimed to neutralize inline links, but
  GFM autolinks a bare `scheme://host` with no delimiters at all, so nothing
  in that strip could reach one; `~~strike~~` used a character outside the
  set too. A friend's stderr is attacker-influenced text — the artifact under
  review steers what the CLI prints. URLs are defanged visibly rather than
  deleted, since the host is usually the useful part of an auth error.
- **Two comments contradicted their own code**, both written earlier the same
  day: the §12.2 block still declared the rule to be "this CLI has no
  read-only mode at all" after `sandbox_confine` was added beside it, and the
  `private_dirs` comment still said self-confining CLIs were excluded after
  codex became both.

Left unsettled, and recorded rather than quietly dropped: two deadlocked
claims — that appending extra_args at the end ignores the flag-ordering rule
`build_argv` documents as a verified trap, and that "scratch inside the
isolation directory" means the git worktree of the code under review for a
repo-scope friend. Both had judges on each side.

### crossexam.py, cross-examined

Eleven claims, and the friends refuted three of each other's rather than
nodding them through. Six upheld and fixed here.

- **A judge was shown its own prior verdict as an anonymous stranger.** One
  set of prior verdicts was built per round and handed to every judge, and
  §5.1 strips the judge's name — so from the first round carrying priors, a
  judge weighing "what did the others conclude" read its own earlier opinion
  back as independent corroboration. Worse than leaking identity: it
  manufactures consensus in the direction each judge already leans, which is
  the exact thing blind presentation exists to prevent. Built per judge now.
- **A re-amended claim could mint a successor id that already existed.**
  `bump_claim_id` derives an id from (number, version + 1) and knows nothing
  about the ledger. When the artifact changes mid-run a loop passes
  `prior=None` — deliberately, so claims settled against the old text are
  judged against the new one — while keeping the accumulated claim list. An
  already-superseded claim is re-seeded contested, amended again, and
  produces the same successor id twice, leaving two different claims under
  one id. Fixed where the id is chosen rather than by asking the caller to
  keep state it discards on purpose.
- **The all-withheld path settled against the full roster.** The other two
  settle paths pass the shrunken one; this passed `specs`, counting friends
  that cannot vote toward quorum — the precise thing shrinking the roster
  exists to prevent.
- **A sub-second remainder dispatched a friend with a zero timeout.** `int()`
  floors, so 0.6s left became `timeout=0`: a friend launched only to be
  killed instantly, spending a call from the budget and reporting a failure
  that marks the run incomplete. Nothing is dispatched under one second now.
- **A loop re-announced a disabled friend every iteration.** The set tracking
  who had already been reported was local to `run_rounds`, which a loop calls
  once per iteration; the spec asks for once per run. It moved onto the
  outcome, where `signatures` already lived for the same reason.
- **A comment was false about the code it cited.** It claimed
  `RepeatTracker` never clears a disabled friend; `record` clears one on any
  success. What actually makes the exclusion permanent is the roster filter
  itself — a friend dropped from `active` is never dispatched again, so it
  never records the success that would re-enable it.

crossexam.py crossed the then-current line cap, so the rules a round applies before
and after dispatch moved to `commands/judging.py`.

### A refused signal crashed the round instead of reporting an orphan

`_signal_group` caught only `ProcessLookupError`, so a `PermissionError` from
`os.killpg` propagated out of `_terminate_group` and out of `run_process`
itself — killing the round rather than the process, and discarding an answer
that in the reported case had already been written and parsed.

Worth recording how it was found. A full test run failed with
`PermissionError: [Errno 1] Operation not permitted`, and that was written off
as interference from a cross-examination running concurrently. Two of the
three failures in that run really were interference; this one was not. agy
raised it independently while cross-examining spawn.py, which is what prompted
reading the exception handling rather than the test output.

EPERM and ESRCH mean opposite things and were being collapsed. ESRCH means
nothing holds that pgid — a clean no-op, the common case for a friend with no
children. EPERM means something *does* hold it and the kernel refused us, so
the group was never reaped and an orphan is exactly what should be suspected.
Reporting that as "gone" claims a cleanup that did not happen. `_group_alive`
had drawn the distinction correctly all along, treating EPERM as alive; only
the signalling half was wrong.

### Every adapter now says how it fails to authenticate, and codex is confined

Four gaps closed, three of which had been sitting behind "nobody has captured
a real failure yet".

- **codex declares auth markers**, captured verbatim from a real 401 on
  2026-08-28. Provoked without touching credentials: point `CODEX_HOME` at an
  empty directory and the CLI finds no auth of its own while `~/.codex` is
  neither read nor written. Not the marker, each for its own reason: `exit 1`
  (codex uses it for a rejected sandbox write and a refused git-repo check
  too), the five-retry reconnect noise, and the websocket connect error a
  plain network failure also prints.
- **claude declares one too**, and as a structured path rather than a stderr
  substring, because under its real flags it states the failure in its own
  JSON: `result: "Not logged in · Please run /login"`. Provoked by denying
  Keychain *read* access to one child process under this runner's own
  sandbox — nothing logged out, nothing written. Deliberately not keyed on
  `is_error` or `terminal_reason: api_error`, which a rate limit sets
  identically; classifying that as auth would stop dispatching a friend that
  only needed to wait.
- **ollama was a category error, not a missing capture.** A local ollama has
  no credentials, so waiting for a captured auth failure meant waiting
  forever. Behind an authenticating proxy it answers 401/403, `http_transport`
  already records the status as `exit_code`, and `classify` already matches on
  exit codes. Those two statuses are specified by RFC 9110 rather than chosen
  by a vendor, which is why declaring them is not the guess §14 forbids.
- **codex now runs under OS confinement** despite having a read-only mode of
  its own. That mode stops it writing and says nothing about what it may
  read: measured, under `--sandbox read-only` alone and asked to list
  `~/.ssh`, it listed the directory; under the sandbox the same request
  returns "the filesystem sandbox denied access". Opt-in per adapter via
  `[sandbox] os_confine`, because blanket confinement would break claude.

Found while doing it: a confined friend could not read its own prompt or
output schema. Both are written to the run directory rather than the friend's
isolation directory, so codex died with `Failed to read output schema file`
the first time it ran confined — opencode had never hit it because it declares
no schema flag. The two files are granted individually rather than by
directory: that directory also holds every other friend's prompt and captured
output.

## 0.1.4

**Upgrade from 0.1.1–0.1.3 if you run `codex`, `claude` or `agy`.** Two holes
in the confinement boundary were open in every one of those releases, and one
of them was announced as closed when it was not:

- **Those three friends inherited every secret you export.** Environment
  filtering was gated on the same condition as filesystem confinement, so the
  three CLIs that confine themselves received no filtering at all. A read-only
  flag stops a CLI writing files; it does nothing about what it can read out
  of its own environment, and an artifact that talks a friend into echoing
  `env` sends every exported token to a model provider. The allowlist 0.1.1
  introduced — and whose arrival that release announced as closing this hole —
  only ever applied to `opencode`.
- **A binary in `~/bin` granted the whole home directory.** A CLI installed as
  a real file in `~/bin` or `~/.local/bin` — the normal shape for a
  curl-installer — was granted `(subpath "/Users/<you>")`, read. That is the
  exact thing this module's docstring says confinement removes.

The rest of this release is the tool being run against its own source, which
is how all of it was found: `opencode` had never once been dispatched
successfully, and a cross-examination of `normalize.py` returned six defects
including a regression introduced three commits earlier.

### A timeout bounded how long a friend ran, not what it cost

c-0002 from the same cross-examination, which the judges ruled out of scope
because it lives in spawn.py rather than in the artifact under review. It was
parked rather than dismissed, and it was real.

stdout, stderr and HTTP response bodies were accumulated with no ceiling. The
documented timeout bounds how LONG a friend may run and says nothing about how
much memory it may make the runner hold -- and friends are dispatched
concurrently, so it was never one friend's memory at stake. A model looping on
generation, the failure this codebase already designs around elsewhere, is the
realistic way to reach it. Measured: an uncapped stream accumulated 13MB where
the cap now holds it to the ceiling exactly.

Each stream is bounded at 32MiB, orders of magnitude above a real critique.
Output that hits the ceiling is never offered to the parser, matching the rule
a timeout already follows and for the same reason: a truncated answer can
still parse, and reporting a friend's partial answer as its whole answer is a
worse failure than reporting none. The run records `output_truncated`, because
a short stdout beside a long duration is otherwise indistinguishable from a
friend that simply said little.

On the HTTP side it was specifically the success path that was unbounded --
the error path beside it had capped its body at 500 bytes all along.

Found while fixing it: the early-answer probe joined the entire stdout buffer
on every 50ms poll, which is quadratic across a run. Affordable to overlook
only while output was unbounded in the first place; it now settles the same
question from the last chunk without joining anything.

spawn.py crossed the then-current line cap, so process-group reaping moved to
`procgroup.py`.

### normalize.py, cross-examined

Six defects in the module that parses untrusted friend output, found by
pointing the tool at it with codex, claude and agy. Three were HIGH and
settled unanimously; all six were reproduced here before being fixed.

- **The early-answer stop discarded the answer it existed to preserve.**
  Shipped three commits earlier. Breaking the wait loop is followed by a
  process-group sweep, so the exit code becomes the signal *we* sent, and
  `if returncode != 0` marked the friend failed: measured
  `normalize succeeded: True` beside `failure_reason: exit -15`. agy's
  answer-then-hang path went from a slow success to a fast failure, which is
  worse than the hang it replaced. The existing test could not see it — its
  payload was agy's ERROR object, which fails normalization anyway, so a
  discarded answer and a preserved one looked identical.
- **The trailing-comma repair was quadratic on exactly its stated input.**
  `(?:,\s*)+(?=[}\]])` carried the note "Verified linear with this
  pattern", and is — when the comma run ends in a bracket. When it does not,
  every start position rescans the run: 16k commas took 7.5s against 0.3ms
  for the same count with a bracket. The cited threat, a repetition-looping
  local model, emits the unbracketed case; and `normalize()` runs *after*
  the process is killed, so that cost lands past the timeout meant to bound
  it. Replaced with a single linear pass.
- **That pass is also string-aware**, which the regex could not be:
  `{"a": "x, }"}` was rewritten to `{"a": "x}"}` — valid JSON, silently
  different value. Repair is structural and has no business editing content.
- **"Latest first" never fixed the codex progress bug it claimed to fix.**
  `extract_json` ranks globally by tier and short-circuits on tier 0, so
  ordering only breaks ties. Schema-valid progress narration (tier 0, carries
  `findings`) beat a real `{"no_findings": true}` answer (tier 2) from any
  position — including with the real answer first. An ordered source now
  takes the first candidate that succeeds under the contract; a single
  document keeps tier ranking, so a stray marker still loses to real findings.
- **An envelope rule could not express the match its own comment described.**
  codex.toml documented "the item.completed event whose item.type is
  agent_message" and declared only the first half, so it matched every
  item.completed — reasoning, command-execution and file-change items
  included. Verified live: a reasoning item's text was extracted as the
  answer. Rules take an optional second condition now.
- **The Envelope docstring reasoned from a false premise**, claiming all five
  shipped adapters declare an envelope and that the no-envelope path is
  reserved for adapters nobody has run. ollama declares none and takes that
  path on every run.

normalize.py crossed the then-current line cap during this, so the envelope machinery
moved to `envelopes.py` — "where the answer lives" apart from "turn text into
a validated payload".

### opencode had never been dispatched, and could not have been

The first crossexam to include `opencode` — the one adapter with no schema,
no read-only mode of its own, and therefore the only one that runs under OS
confinement. It failed in 0.06 seconds, in every round, with `error: An
unknown error occurred (Unexpected)`. It had never been dispatched in a real
run before, so the confinement path shipped in 0.1.0 had never executed
against the CLI it exists for.

Three separate things were wrong, each hidden behind that one message:

- **It could not write its own log.** opencode opens
  `~/.local/share/opencode/log/opencode.log` before it will do anything and
  exits if the open fails. The profile granted that directory read-only.
  Adapters can now declare `[sandbox] write`, which stays empty for every
  adapter that has not earned it.
- **It could not read the temp directory.** It runs on bun, which keeps its
  cache directly in `$TMPDIR` — so granting the friend's own isolation
  directory, which lives there, was not enough. Adapter paths now expand
  `$TMPDIR` as well as `~`, and a declared path is granted alongside its
  real path: `/tmp` is a symlink to `/private/tmp` and `$TMPDIR` sits under
  `/var/folders`, so granting only what was written granted nothing at all.
- **It had no credentials.** `opencode auth list` reports where it actually
  looks, and on the machine this was captured from it named `GEMINI_API_KEY`
  and `HF_TOKEN` — neither in the adapter's allowlist, so a confined
  opencode reached its provider and was refused by it.

With those fixed it starts, runs for a minute rather than dying instantly,
and reaches its provider. It also produced the first auth marker of the kind
§14 actually describes — a CLI naming the failure in its own structured
output, `{"error":{"name":"ProviderAuthError"}}`, rather than the stderr
sentence agy needed. agy's remains a recorded divergence; opencode's is the
shape the spec asked for.

The machinery around the failure behaved correctly throughout, which is worth
recording: the environment was filtered to eight variables, the repeat
tracker disabled opencode after two identical failures, the run reported
itself incomplete, and the shrunken roster was named in the report.

Cross-examining `sandbox.py` immediately afterwards found three defects in
that fix, and the corrections collapse into something better than what it
replaced:

- **The `$TMPDIR` grant exposed every other friend.** Isolation directories
  are created there, so reading it meant reading other friends' trees and
  every other same-user temporary file.
- **One log file was paid for with the whole state directory**, which
  outlives the run: a friend could corrupt saved sessions or auth state that
  a later run depends on.
- **The isolation directory itself was the one path never resolved**, so on
  macOS the profile granted `/tmp/...` while the kernel saw
  `/private/tmp/...` — a friend denied write access to its own working
  directory, by the module that states the resolve-paths rule for
  everything else.

A confined friend now gets a private scratch and state directory *inside*
its isolation directory (`TMPDIR`, `XDG_DATA_HOME` and their neighbours), so
opencode writes its log where the round deletes it and needs no grant
outside the boundary at all. Redirecting where a CLI thinks its state lives
beats widening the sandbox to reach the real one.

### Three friends were inheriting every secret you export

The same crossexam's highest finding, and the only one in this batch that
was not about a change made an hour earlier.

Environment filtering was gated on the same condition as filesystem
confinement — `if not adapter.readonly_argv` — so codex, claude and agy, the
three CLIs that confine themselves, received no environment at all and
inherited the operator's whole shell. A read-only flag stops a CLI writing
files; it does nothing about what it can read out of its own environment,
and an artifact that talks a friend into echoing `env` sends every exported
token to a model provider. The allowlist 0.1.1 introduced — and whose
arrival that release announced as closing this hole — only ever applied to
opencode.

Every exec friend is filtered now. Verified against all three before the
coupling was cut: each authenticates under the allowlist, because their
credentials are files under `HOME` rather than variables.

The run's record follows dispatch again — every exec friend counted, HTTP
friends excluded because there is no child process to deny anything to, and
a host with no sandbox now reports that the filesystem is unconfined *while
the environment is still filtered*. The previous wording understated the
protection as badly as the original overstated it.

### Waiting twelve minutes for an answer already in the pipe

agy, on its error path, writes its JSON and then does not exit until its own
`--print-timeout` elapses. Measured across seven cross-examinations: eleven
successful runs exited about 2.5 seconds after the work they reported, and
all three hangs exited at 906 seconds having reported 163, 372 and 482 — up
to twelve minutes spent waiting for a process that had already answered.

Nothing on this side was wrong: stdin is closed, and §11.3's timeout
reconciliation was doing exactly what it says. So the fix is narrow. A
`json_path` adapter's contract is that stdout **is** one JSON object, so
once it parses, the answer is in hand and the run stops waiting. Restricted
to that envelope kind on purpose: an NDJSON friend streams events and codex
emits a schema-shaped progress message *before* its real findings, so the
same check there would truncate the thing it is waiting for. The run records
`stopped_after_answer`, because a reader comparing a friend's wall clock
against the CLI's own report of itself should not have to guess.

Found while testing it: `cwd=str(cwd)` turned `None` into a literal
directory named `None`, and Popen's `FileNotFoundError` was reported as
**"binary not found"** — sending a reader to hunt for a CLI that is
installed. It now names whichever is actually missing.

### `--merge orchestrator` works with `--mode loop`

It was refused, and the refusal was honest about why: a loop halts once per
iteration and would resume into mid-flight state — a budget, a dry-round
streak, a claim set — that the build had never reconstructed.

All of it was already on disk. States and notes in `run.json`, verdicts in
the ledger, discard signatures derivable from those, iteration and streak in
the metadata. The one thing genuinely missing was that **the halt path
recorded none of it**: the completion path wrote `iterations_run`,
`dry_streak` and `claim_states`, so a resumed loop re-entered knowing only
that it had been interrupted. Both paths build the run's metadata the same
way now — a halted directory a resume cannot read is worse than no halt.

A resumed loop re-enters the iteration it halted in, inherits what earlier
iterations decided, and carries on; the next iteration halts for its own
adjudication.

### A binary in `~/bin` granted the whole home directory

From the same crossexam, and confirmed by running it before it was fixed: a
CLI installed as a real file in `~/bin` or `~/.local/bin` — the normal shape
for a curl-installer or a single-file binary — was granted
`(subpath "/Users/<you>")`, read. That is the exact thing this module's own
docstring says confinement removes.

The rule was "the parent of any directory named `bin`", which is right for a
symlink into an installation (`~/.opencode/bin/opencode` needs the 61MB
`node_modules/` beside it) and wrong for everything else: a real file in
`~/bin` resolves to `~/bin`, whose parent is your home directory. An install
root must now look like one — a `lib`, `libexec`, `share` or `node_modules`
sibling — and the home directory is never one, whatever it happens to
contain.

Two related corrections, both about the boundary describing itself
accurately:

- The generated profile is written into the run directory **to be audited**,
  and its comment claimed link-local and cloud-metadata endpoints were
  denied while emitting only a `localhost` rule. It now says outright that
  SBPL cannot express a numeric address and that `169.254.169.254` stays
  reachable.
- `--ro-bind-try` was documented as used "throughout" when the system set
  and the working directory bind hard, and `read_paths` was documented as
  "the resolved path of the binary" when it carries up to three directories.

The rest of the fifth crossexam's findings -- the eight the 0.1.2 batch left
open -- plus two defects that surfaced while testing them.

- **Friends reviewed the live file, not the frozen copy.** §4.1 lists "the
  frozen artifact" among a friend's three inputs and `artifact_hash`
  attests to those bytes, but every dispatch re-read the live path, which
  made the frozen read dead code. An artifact edited between a halt and a
  resume was judged while run.json still reported the original hash, and
  `afriend resolve` compared locations against a copy nobody had reviewed.
  A loop re-freezes per iteration instead, so the copy, the hash and what
  friends read are the same bytes.
- **A `fixed` resolution could be accepted for a file nobody touched.** The
  snapshot was taken only for repo-scope friends or `gate`, but `afriend
  resolve` accepts any run directory and never reads the mode -- so a
  doc-scope crossexam recorded no snapshot, every location verified as
  `unverifiable`, and `unverifiable` does not refuse `fixed`. The snapshot
  is taken whenever there is a repository; it is a commit object built from
  the index, with no worktree and no checkout.
- **A symlinked artifact reviewed the wrong repository.** Repository
  selection resolved the artifact before asking git which repo enclosed it,
  so `repo-A/docs/spec.md -> repo-B/spec.md` snapshotted repo-B. The path
  the operator names picks the context; the link's target supplies only the
  bytes.
- **Two concurrent resumes shared one run directory.** A fresh run is
  protected by the "already exists" refusal, but a resume deliberately
  reopens a directory that has one, so two CI workers could dispatch the
  same round twice, append duplicate records to one ledger, and overwrite
  each other's run.json. An advisory lock now refuses the second with an
  explanation.
- **The fan-out was unbounded**: one thread, one process and one worktree
  per friend, all at once. A large generated roster could exhaust file
  descriptors or a provider's rate limit before repeat detection saw a
  single failure. Bounded at eight, which a hand-written roster never
  reaches.
- **The wall-clock ceiling bounded the gaps between rounds, not the run.** A
  friend dispatched a second before it expired ran its own full timeout
  past it -- 900 seconds by default -- and a run that finished in that
  round reported no ceiling hit at all. Every friend's timeout is capped at
  what is left.
- **Nothing had ever executed the wall-clock branch.** `Budget.out_of_time`
  had a unit test; the code that calls it did not, because an end-to-end
  run cannot wait two hours and the check read the clock directly.
  `AF_CLOCK_OFFSET_S` moves the clock the run reads, so the same arithmetic
  runs against a clock a test can advance.

Two more, both found by writing that test:

- The first clock injection cancelled itself out -- the offset was added to
  the run's start as well as to each reading -- so the ceiling could never
  be reached however far the clock was moved.
- A ceiling hit in the iteration loop exited **1**, not 11: `ceiling_hit`
  was only ever read off the crossexam outcome, and a budget exhausted
  before any crossexam existed left the operator with a plain failure and
  no mention of the ceiling they had set.

Also: dead comments and a dead type alias left by the `commands/` split are
gone, `JUDGING_MODES` is defined once rather than twice, `cmd_run` crossed
the line cap again and the revision an iteration reviews now lives in one
function (`environment.freeze_revision`), and the README installs from PyPI.

## 0.1.3

**The first release published to PyPI.** 0.1.2 was tagged but never
published, because building it turned up the reason to look: `afriend
--version` printed `0.1.0` from a 0.1.2 wheel.

- **The reported version had drifted two releases.** `__version__` was a
  literal in `__init__.py`, and nothing compared it to `VERSION` -- the
  file that drives the build, the plugin manifests and the wheel metadata
  all agreed with each other while the string a user actually sees did not.
  It is derived now: from `VERSION` in a checkout, from distribution
  metadata when installed. `scripts/check_version_sync.py` checks it
  alongside the manifests, so the next spelling that reintroduces a literal
  fails the gate.
- **The test for it passed by construction.** `test_af_reports_version`
  asserted the output started with `"afriend "` and never looked at the
  number, which is exactly how an installed 0.1.2 could print 0.1.0 with
  the suite green. It compares the number now.

## 0.1.2

**Upgrade from 0.1.1 if you use `--mode gate`, `--mode loop`, or run friends
confined.** A gate could clear without checking anything, a run's record of
withheld secrets could describe a filter that never ran, and a loop could
judge one revision's wording against another revision's code.

Everything below was found by pointing the tool at its own source: five
cross-examinations, each one reviewing the file the previous one's fixes had
just changed. Every round found defects in the round before it.

### Doc scope was the unguarded half

Every friend is downgraded to doc scope when the artifact is not inside a git
repository. That path had never been exercised against a real CLI. Two
defects, found by finally running it:

- **codex could not run in doc scope at all.** It refuses to start outside a
  git repository — `Not inside a trusted directory and --skip-git-repo-check
  was not specified` — so it failed before the model saw the prompt, every
  time. Adapters can now declare `doc_argv` for flags a CLI needs in order to
  *start* in a bare directory.
- **Doc scope dropped the CLI's own read-only mode.** The reasoning was "doc
  scope has no repo to protect", which skips that there is still a
  filesystem — and that doc scope is exactly where a read-only-capable CLI
  gets no OS confinement either. Measured, not inferred: real codex in a bare
  directory with no `--sandbox` flag, asked to write outside its working
  directory, did so on the first attempt. Fixing only the first defect would
  have turned "fails to start" into "starts able to write anywhere", so the
  two ship together.

### A crossexam that produced zero verdicts

Pointed `--mode crossexam` at `verdicts.py` with codex, agy, and claude. Two of
three friends failed every round; the failures were worth more than the
verdicts would have been.

- **claude had never produced output under a schema.** `--json-schema` takes
  the JSON itself; every adapter was handed a file path, so claude failed
  before the model saw anything. The third of three native-schema adapters
  found broken the same way, after codex and agy in 0.1.1 — and for the same
  reason: no test ran a real CLI under a schema. Adapters can now declare
  `schema_inline`, and claude's envelope reads `structured_output`.
- **Discard fired on nothing.** Once the repeat tracker disabled both other
  judges, two more rounds ran with nobody dispatched and every claim ended
  `discarded` — "judges looked twice and could not verify" — when no judge
  had looked at all. A judge the tracker withholds now counts as one that
  never reported (§7.2 M12), those claims read `incomplete`, and a round in
  which every judge is withheld ends the run instead of burning the rest.
- **Discard compared non-consecutive rounds.** `unproven` in round 2,
  `contested` in round 3, `unproven` again in round 4 was compared against
  round 2 and discarded — closing a claim with live disagreement on the
  record. codex raised this while reviewing the file; a reachability test
  confirmed it before it was fixed.
- **The first real auth marker.** agy's login had lapsed, and it said so only
  on stderr: `Error: authentication required. Run 'agy' to log in, then
  retry.` §14's marker kinds could not express that, so adapters may now
  declare `stderr_contains` — restricted to a sentence captured verbatim from
  a real failure (recorded as a divergence in the spec's §20). Beside it,
  the near-miss that must not be adopted: `authentication timed out` is what
  agy says when it cannot *reach* the auth endpoint.

### What the second crossexam found

The same three friends, run again on `verdicts.py` after those fixes. All
three succeeded in rounds 2 and 3 -- twenty verdicts, two claims
settled-upheld -- and the round-1 failures, the verdicts, and a two-day-old
process found along the way each turned into a fix.

- **codex's real findings were dropped.** Under `--output-schema` codex emits
  its progress narration as `agent_message` events, each forced into the
  schema's shape: "I'm inspecting the repository..." arrived as a valid
  findings object with `location: null`, before the answer. The normalizer
  keeps the first candidate that ranks best, so the progress line was
  recorded as a claim (and duly discarded) and the answer -- a high-severity
  finding about amendment wording -- was never seen. An NDJSON envelope now
  offers its matches latest-first: in an event stream the final event is
  the answer.
- **The abort handler could deadlock the run it was aborting.** A second
  SIGTERM pending while the handler's first invocation was inside
  `abort_event.set()` ran the handler again, nested, on the same thread; the
  nested `set()` blocked on the lock its own caller held. Found as a process
  from a crossexam two days earlier, still alive with five invocations
  nested on its main thread; reproduced with three back-to-back signals --
  GNU `timeout` alone sends two. The handler is re-entrancy guarded now, and
  a probe forces the interleaving in the suite.
- **`incomplete` was run-level.** The fix above made a withheld judge count
  as one that never reported -- for every below-quorum claim in the run, so
  one unrelated friend's failure marked claims whose own judges had all
  reported `incomplete` and reset their discard signatures. The judges of
  this run raised it. It is per claim now: a claim is `incomplete` when one
  of *its* judges was silent; the run-level flag stays.
- **`discarded` cleared a gate.** The spec says everything but
  `settled-refuted` needs a Resolution; the comment above the set said only
  `settled-refuted` clears; the set also cleared `superseded` and
  `discarded` (settled-upheld by both judges). A discarded claim is one
  nobody could check, and a gate passing on that is the failure the tool
  exists to prevent -- it blocks now. `superseded` is exempt rather than
  clearing: its successor carries the question.
- **The late-amendment note fired for any downgraded amendment**
  (settled-upheld by both judges): the evidence rule rewrites `amended` to
  `unproven` in any round, and the detector could not tell that from the
  final-round rewrite, so a round-2 amendment with unverifiable evidence was
  reported as "in the final round ... counted as upheld", with advice to
  add rounds that would change nothing.
- **agy's own error message was hidden.** `{"status":"ERROR","response":"",
  "error":"timeout waiting for response"}` was reported as "the adapter may
  need an envelope path". A json_path envelope can now name an
  `error_path`, read only after normalizing has failed, so the failure
  leads with what the CLI said. agy then stayed alive until the runner's
  900 s ceiling and left orphans -- its problem, but a fifteen-minute round
  is the cost.

### What the third crossexam found

Run again after those fixes, same roster, same file. Every friend succeeded
in every round; nine claims, twenty verdicts, seven settled-upheld, none
garbage, none discarded. Two of the upheld claims changed rules that were in
the spec.

- **A final-round amendment was rewritten to `upheld`.** The rule existed so
  no successor could be created with no round left to judge it. On this run
  both judges of one claim said its headline was false, amended it in the
  final round, and the rule turned their rewrites into `settled-upheld` --
  "judges unanimously agreed the claim stands". It was also wrong in loop
  mode (claims carry into the next iteration) and for a lone judge (whose
  amendment could never produce a successor). Gone: an amendment is a
  rewrite in any round, a lone judge's included; a successor created by the
  last round stays `incomplete`, is named in the report, and blocks a gate.
- **The ledger identity dropped the model.** `codex:ops:gpt-5` and
  `codex:ops:gpt-5-mini` shared `codex/ops`: quorum counted two judges,
  one verdict survived, and which one depended on `--friend` flag order --
  flag order could clear a gate. The identity is the roster unit now
  (`cli/lens`, then `@model` and `+effort` when set; existing ledgers are
  unchanged), a repeated entry is refused up front in any mode that judges,
  and `judges_for` counts each identity once.
- **A claim nobody could judge was `discarded` after two rounds**, because
  its verdict signature was `()` both times and `() == ()`. "Judges looked
  twice and could not verify" was being said of a claim no judge was shown.
  An empty signature never discards.
- `gate_blocked` and `summarize` had no callers -- the gate is
  `resolutions.blocking_claims`, whose docstring still said `discarded`
  clears. Both deleted, docstring fixed. `loop_should_terminate` now states
  the precondition its caller meets, and the filter that meets it has a
  test. The judge prompt says an amendment must leave the claim's evidence
  standing, since a successor inherits it.

### What a review of that batch found

The amendment and identity changes above were right about `crossexam` and
wrong about `loop`, where claims carry from one iteration to the next.
Reproduced by running the tool, all three:

- **A superseded claim was re-judged every iteration.** Each iteration
  re-seeded every claim `contested`, so a claim an earlier iteration had
  already settled was judged again -- and an amended one produced a
  successor under the same id each time, since claim ids count versions
  rather than records. A three-iteration loop wrote `c-0002@2` into the
  ledger three times. Terminal is terminal across iterations now.
- **A claim no friend could judge held the loop open forever.** An amended
  claim's successor inherits both the author's and the amenders' origins,
  which on a two-friend roster is the whole roster: no independent judge,
  `unproven` for good. Since the empty-signature fix above (correctly)
  stopped discarding it, the loop waited for it and ran to its iteration
  ceiling -- twelve judging rounds where three would do. A loop no longer
  waits on what no further iteration could change; the claim is still
  reported and still blocks a gate.
- **"No round was left to judge it" was told to the operator once per
  iteration**, for a successor the next iteration went on to carry. That
  ceiling is per iteration; the message now waits for the last one.

Three more from the same review, none loop-specific:

- The run-level `incomplete` flag was being set for an unjudgeable
  successor. It means "a required friend failed" (§7.2 M12) and the report
  says so in those words; no friend had failed.
- The duplicate-identity guard ran before the preset filled efforts and
  before `--model`/`--effort` (§10.1 layer 4), so it missed the collisions
  those create -- `--friend codex:ops:gpt-5 --friend codex:ops --model
  gpt-5` resolves to two friends with one identity -- and it refused
  rosters whose duplicate entry `--max-friends` would have dropped. It runs
  last now, on the roster the run will actually use.
- **`--model` and `--effort` were not restored on resume.** Now that they
  are part of the ledger identity, a run resumed without them re-resolved
  its friends under identities the ledger did not hold, and a claim whose
  author no longer matched its origin was handed its own claim to judge.

Also: an unsettled claim with no verdicts says why instead of sitting under
a heading promising both sides quoted, and `Rounds run:` counts the highest
round the run reached rather than the last iteration's -- which, once a
final iteration could legitimately run no judging round, read "1" for a run
that had just spent eight.

### What the fourth crossexam found

Pointed at `commands/crossexam.py` -- the file the last two commits
changed, and the first target that was not `verdicts.py`. Nine claims,
eight settled-upheld, one settled-refuted. Almost all of them were about
the loop carry-over those commits had just introduced.

**A loop block carried states and nothing else**, and four claims followed
from that one omission. Each iteration built a fresh outcome, so a claim
deadlocked in iteration 1 was printed under "Unsettled" with "No verdict
was cast on this claim" -- the line added one commit earlier -- while both
judges' reasoning sat in the ledger; later blocks' judges never saw earlier
arguments; a required friend's failure in an earlier iteration was
forgotten, so a run that lost a judge reported itself complete; and the
discard rule, which needs two consecutive rounds, could never fire in a
loop whose blocks hold one judging round each. A block now inherits the
previous one's verdicts, notes, discard signatures and `incomplete` flag.

**Carried states were not tied to the artifact.** A loop re-reads the
artifact precisely to pick up a revision, and a claim settled against the
old text is not settled against the new one -- carried across an edit, the
report goes on naming a defect the edit may have removed. The carry now
stops at any change to the artifact, and the run says it re-opened those
claims.

**A friend the repeat tracker disabled was still counted as a judge.**
`RepeatTracker` never clears a disabled friend, so it was recorded as
"missing" every round for the rest of the run: its claims were pinned at
`incomplete`, never `unproven`, so never discardable, so a loop could not
converge on them. It leaves the judging roster now -- quorum counts who can
still vote -- and the shrunken roster is reported rather than implied. The
judges refuted the claim's headline (it does not pin *every* claim, and
disabled friends were never re-dispatched) and upheld the narrower defect.

Three smaller ones from the same run:

- `_prior_verdicts_by_claim` never reduced to one verdict per judge, so
  from round 4 a judge's prompt showed one judge's round-2 and round-3
  verdicts as two anonymous reviewers -- §5.1 strips the judge and carries
  no round. A manufactured consensus, in the prompt the next judge reads.
  The file's own comment listed three sites where this accumulation bug had
  been fixed; this was the fourth.
- The call-budget precheck counted judges the repeat tracker would drop, so
  a run could stop `budget-exhausted` with room for the one judge it would
  actually have dispatched.
- A successor created at the last round of a *non-final* loop block was
  left `contested` with no note, on the assumption the next iteration would
  judge it. The loop can stop first, and such a successor cannot even hold
  it open, so the report said "judges disagreed" about a rewrite no judge
  had seen.

### What the fifth crossexam found

Pointed at `commands/run.py`. Thirteen claims, twelve settled-upheld. Two
of them are the worst kind this tool can find: a run record that asserts a
protection that did not happen, and a gate that cannot gate exiting 0.

- **`env_withheld` described a filter that had not run.** It is the run's
  record that secrets were kept from confined friends, and it was computed
  by passing `--pass-env` into `childenv.withheld`'s *adapter* slot -- so
  the adapter's own pass list was never consulted. opencode declares six
  API keys in its `pass` list, dispatch hands all six to the child, and all
  six were reported as withheld. Nothing checked whether a confinement
  mechanism existed either, so an unsandboxed run that filtered nothing
  still produced a full withheld list. Both fixed: the list is computed per
  friend from the same inputs dispatch uses, only when a mechanism exists,
  and a name counts as withheld only if no confined friend received it. A
  run with no mechanism now says the environment was NOT filtered.
- **§8.3 was a comment, not a rule.** One friend plus `crossexam`, `gate`
  or `loop` must hard-error (exit 3); the code appended a downgrade and
  ran. With one friend no judge is independent of any claim, so a `gate`
  run settles nothing, blocks on nothing, and exits 0 -- CI reads "gate
  clear" from a run that structurally could not check anything. The
  `DEGRADED_MODES` constant that encodes the rule existed and was wired to
  nothing.
- **A loop could review two revisions at once.** The snapshot was taken
  once before the loop, so re-reading the artifact each iteration asked
  friends to judge new wording while repo-scope friends were checked out at
  the old commit: claim and evidence from different revisions, in one
  verdict. The repository is re-snapshotted when the artifact changes.
- **Resume re-resolved the roster.** "A resumed run rebuilds its whole
  configuration from run.json" was not true: `resolve_friends` ran
  unconditionally, the recorded roster was never consumed, and
  `max_friends`, `pass_env`, `unsafe_extra_args`, `i_accept_unsandboxed`
  and `keep` were not restored either. A roster file edited between halt
  and resume, or a CLI installed in the meantime, could change quorum.
- **A test passed by construction**: `test_a_friend_that_recovers_is_not_
  disabled` used two friends that never failed, so the tracker it meant to
  exercise was never engaged.

Two existing tests had encoded the pre-§8.3 behaviour -- a single-friend
gate exiting 1, and the preset test running one friend -- and were changed
to two friends. `cmd_run` crossed the then-current line cap with the refusal in it,
so which friends a run dispatches now lives in one place,
`friends.roster_for_run`, including both rules that can stop a run before
anything is spent.

A duplicated block in `cmd_run` also ran the resolve/validate/downgrade
sequence three times over, calling `resolve_friends` three times and
reassigning `specs` *after* confinement had been computed from an earlier
copy. Visible in any real report as the same downgrade printed twice.

## 0.1.1

**Upgrade from 0.1.0 if you use `codex` or `agy`.** Both shipped schemas were
rejected by every schema-enforcing CLI, so cross-examination could not work
with either friend. Found by pointing the tool at its own source with a real
roster — the first thing it did was fail two of its three friends.

- **codex had never produced output under a schema.** OpenAI's strict
  structured-output mode requires `additionalProperties: false` on every
  object and `required` naming every property; neither schema had them, so
  the API rejected the request before the model saw the prompt.
- **agy failed every judging round.** The verdict schema's
  `evidence_assessment` enum contained `null`, which it rejects outright.
- The friend prompt contradicted the fixed schemas, telling friends to send
  one of `findings`/`no_findings` when strict mode requires both.

None of this was caught by 700 tests, because every test used the fake friend
(no schema) or ollama (`schema=False`).

### Confinement

Two holes straight through the middle of the sandbox, from the same review:

- **The environment was not filtered.** A confined friend inherited every
  secret exported in the runner's shell — 61 variables on the machine this
  was found on, four of them API tokens for unrelated services — readable
  without touching a single forbidden path. It now receives an allowlist,
  and the run records how many names were withheld (names only, never
  values).
- **Host-local networking is denied on macOS.** `127.0.0.1` was reachable, so
  a local database or another dev server was one request away.

Still open, and stated rather than implied: SBPL cannot filter numeric IPs, so
cloud metadata stays reachable on macOS; `bwrap` has no selective filtering at
all, so Linux keeps shared networking. Both need an egress proxy, which was
investigated and deliberately not built -- the macOS half is viable
(`localhost:PORT` does parse, and codex and agy both honor `HTTPS_PROXY`), the
Linux half has no stdlib answer, and the whole thing stops lateral movement
rather than exfiltration, since a friend must reach its own model to work.
`sandbox.py` records the measurements so the next attempt starts from them.

- The binary allowlist assumed a CLI's libraries sit beside its executable.
  They do not for any package-manager layout — `opencode` keeps a 61MB
  `node_modules/` beside `bin/`.

## 0.1.0

First release. Dispatches a spec, plan, or review to other agent CLIs as
independent adversarial reviewers, then makes them argue about what they
found.

### Modes

- **`report`** — one round, every friend critiques in parallel, claims merge
  into one ranked report.
- **`crossexam`** — friends then judge the claims they did not write, blind,
  until each settles, deadlocks, or hits a ceiling.
- **`gate`** — every non-advisory claim that did not clear needs an explicit
  resolution. This is the mode that fails a build.
- **`loop`** — repeats until two consecutive rounds surface nothing new.

`afriend resolve` records a resolution and re-reports the gate. `afriend
init` writes a roster from what is installed. `afriend doctor` reports what
each friend can actually enforce, with `--json` and `--gc`.

### Friends

`claude`, `codex`, `agy`, `opencode`, and local models over `ollama`'s HTTP
API. Adapters declare what each CLI can enforce rather than assuming: schema
support, read-only mode, whether its effort level can be verified at all.

### What it refuses to fake

Most of the design work went into *not* claiming more than is true.

- **Blind presentation.** A judge is never told who wrote a claim — not the
  friend, and not the lens either, since round-robin assignment makes a lens
  identify its author just as surely.
- **Deadlocks are reported, never resolved.** Two judges who disagree leave
  the claim `deadlocked` with both sides quoted verbatim. Nothing here is
  entitled to break the tie by majority.
- **A judge that could not check the evidence settles nothing.** A verdict
  carrying `unverifiable` is downgraded before anything counts it, so no
  claim is ever dismissed on the strength of nobody having looked.
- **A resolution is an attestation.** The runner cannot know a defect is
  gone; it checks whether the location you named changed, and says which of
  three things it found. The one thing it refuses is `fixed` at an unchanged
  location.
- **Deduplication is judgment.** `--merge exact` under-merges on purpose;
  `--merge orchestrator` halts with exit 10 and asks.
- **No `--max-spend-usd`.** A dollar cap needs per-CLI cost reporting nobody
  has captured, and a flag that silently never fires is worse than none.
  `--max-calls` is derived from your roster and actually enforced.

### Containment

A CLI with no read-only mode of its own runs under `sandbox-exec` (macOS) or
`bwrap` (Linux), or it is refused. The macOS profile was built by
measurement, not documentation. What it removes is other repositories, SSH
and cloud keys, and the rest of your home directory; what it cannot remove is
network access and the friend's own credentials, which it needs to work at
all — stated plainly rather than implied away.

Rosters supply values only. There is no mechanism for a file to inject a
flag, and a repo-local roster is never loaded automatically: a cloned
repository does not get to choose who reviews it.

### Known gaps

- **claude and agy are still not OS-confined**, and each for a stated reason
  rather than for want of effort. claude keeps its credentials in the macOS
  Keychain and reports `Not logged in` under any profile that does not grant
  `~/Library/Keychains`; granting it would hand a friend every credential the
  operator has, which is worse than the gap. agy is left untested on purpose,
  because provoking its re-authentication has already cost one login. Both
  still engage their own read-only modes in every scope, so neither is
  unrestrained — what they lack is read protection.
- `quorum_partial` (spec §7.2) is not emitted, and will not be: the
  per-claim state and the run-level `incomplete` flag already say it, and a
  third spelling is one more thing to keep true.

See `docs/superpowers/specs/` for the design and its recorded divergences.
