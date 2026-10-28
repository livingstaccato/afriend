# Windows provider startup verification

Goal: install the real Claude, Codex, OpenCode and Pi CLIs on native Windows and
prove that their executables start through afriend, canonical adapter arguments
are accepted (or explicitly fail closed), and invalid invocations fail promptly
with the expected diagnostic. No login, secret, model response or live review is
required. AGY and Ollama are outside this four-CLI startup matrix.

- [x] Add a bounded startup verifier using afriend's real executable resolution,
  argument construction and process runner; validate its pass/failure assertions
  with real local subprocess tests before adding the implementation.
- [x] Add four native Windows CI matrix jobs, latest npm harness releases
  (optional explicit version overrides), Node LTS,
  isolated credential-free profiles, strict failure propagation, and uploaded
  stdout/stderr/JSON evidence even on failure. No skip or continue-on-error.
- [ ] Run focused checks and independent review, push the PR update, and watch
  all Windows startup matrix jobs to completion; repair any exposed defects.
- [ ] Document the exact installed versions, observed startup/rejection behavior,
  and limits. Startup coverage does not establish authenticated provider use.
