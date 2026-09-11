---
type: llm
weight: 1
---

This is a GENERIC request. It must NOT activate any afriend skill.

PASS if the response does any of these WITHOUT invoking an afriend skill or
running the `afriend` CLI:

- answers the request directly as ordinary work;
- asks the user for the artifact, file path, PR, or text to look at, because
  none was supplied (this is the expected response when the prompt refers to
  "this" with no attachment) -- asking for the input is NOT activation;
- says the request is outside what it should act on.

FAIL only if the response invokes the `review`, `status`, `configure`, or
`resolve` skill, runs the `afriend` CLI, proposes running `afriend run`, or
otherwise frames the answer as an afriend product workflow. Widened
activation is the regression these cases guard against, so judge the ACTION
taken, not the wording of a request for input.
