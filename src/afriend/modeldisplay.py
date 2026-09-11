"""Operator-facing labels for a friend's provider and model selection.

These two tables were duplicated byte-for-byte in `progress.py` and
`report.py`, which narrate the same run to the same reader -- the live stream
and report.md. Duplicated, a change to §10.1's precedence wording had to be
made twice or the two would disagree about the same run.

Only the DATA lives here. The two modules still build their own strings, and
those conditions differ slightly (progress keys off `spec.model is None`;
report additionally gates on `model_source == "cli-default"`), so folding the
formatting together would be a behaviour change rather than a deduplication.
"""

MODEL_SOURCE_LABELS = {
    "invocation": "invocation",
    "explicit-friend": "explicit friend",
    "roster": "roster",
    "provider-setting": "provider setting",
    "adapter-default": "adapter default",
    "cli-default": "CLI default",
    "recorded-unknown": "recorded model; selection source unavailable",
}
PROVIDER_DISPLAY_NAMES = {
    "codex": "Codex",
    "opencode": "OpenCode",
    "agy": "Antigravity",
    "claude": "Claude",
    "ollama": "Ollama",
}
