"""Offline Pi 1.4.0 process double; never import this into production.

The event framing follows the captured pi_*.ndjson fixtures. Payloads and
retry delays are synthetic, deterministic scenarios, selected by model ID.
Reject unsafe argv rather than letting adapter regressions pass silently.
"""

import argparse
import json
import os
from pathlib import Path
import sys
import time

DENIAL_FLAGS = (
    "--no-extensions",
    "--no-mcp",
    "--no-skills",
    "--no-prompt-templates",
    "--no-themes",
    "--no-context-files",
)


def emit(event):
    print(json.dumps(event), flush=True)


def message(payload=None, *, error=None, stop="stop"):
    msg = {
        "role": "assistant",
        "content": [],
        "api": "openai-completions",
        "provider": "test",
        "model": "offline",
        "stopReason": stop,
        "timestamp": 1793125400000,
        "usage": {
            "input": 10,
            "output": 10,
            "cacheRead": 0,
            "cacheWrite": 0,
            "totalTokens": 20,
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0},
        },
    }
    if error:
        msg["errorMessage"] = error
    if payload is not None:
        msg["content"] = [
            {"type": "thinking", "thinking": "Synthetic reasoning; not an answer."},
            {"type": "text", "text": json.dumps(payload)},
        ]
    emit({"type": "message_end", "message": msg})
    return msg


def main():
    if sys.argv[1:] == ["--list-models"]:
        if (Path.home() / "empty-catalog").exists():
            print("No models available. Use /login to log into a provider via OAuth or API key.")
        else:
            print("provider  model  context  max-out  thinking  images")
            print("test  upheld-a  128K  16K  yes  no")
            print("other  upheld-a  128K  16K  yes  no")
        return 0
    parser = argparse.ArgumentParser()
    for flag in (*DENIAL_FLAGS, "--print", "--no-session", "--offline", "--no-approve"):
        parser.add_argument(flag, action="store_true", required=True)
    parser.add_argument("--mode", choices=["json"], required=True)
    parser.add_argument("--tools", choices=["read,grep,find,ls"], required=True)
    parser.add_argument("--model", default="test/upheld-a")
    parser.add_argument(
        "--thinking", choices=["off", "minimal", "low", "medium", "high", "xhigh", "max"]
    )
    # argparse's --help exits before required-argument checks. A probe must
    # still carry every denial flag, just as Pi's measured capability probe.
    if "--help" in sys.argv:
        if not all(flag in sys.argv for flag in DENIAL_FLAGS):
            return 2
        parser.print_help()
        return 0
    args = parser.parse_args()
    prompt = sys.stdin.read()
    if not prompt.strip():
        parser.error("review prompt must arrive on stdin")
    judging = "--- CLAIMS UNDER REVIEW ---" in prompt
    log = os.environ.get("PI_TEST_LOG")
    if log:
        with Path(log).open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {
                        "model": args.model,
                        "thinking": args.thinking,
                        "judging": judging,
                        "cwd": str(Path.cwd()),
                        "argv": sys.argv[1:],
                        "pid": os.getpid(),
                    }
                )
                + "\n"
            )
    emit({"type": "session", "version": 3, "id": "offline-pi", "cwd": str(Path.cwd())})
    emit({"type": "agent_start"})
    scenario = args.model.split("/", 1)[-1]
    if scenario.startswith("large") and (
        len(prompt) < 200_000 or "END_LARGE_ARTIFACT" not in prompt
    ):
        parser.error("large stdin prompt was truncated")
    if scenario.startswith("hang"):
        time.sleep(120)
    if scenario.startswith("auth"):
        msg = message(error='401: {"type":"auth_error"}', stop="error")
    else:
        if scenario.startswith("retry"):
            failed = message(error="503 Service Unavailable", stop="error")
            emit({"type": "agent_end", "messages": [failed], "willRetry": True})
            emit(
                {
                    "type": "auto_retry_start",
                    "attempt": 1,
                    "maxAttempts": 3,
                    "delayMs": 500,
                    "errorMessage": "503 Service Unavailable",
                }
            )
            time.sleep(0.5)
        if judging:
            tail = prompt.split("--- CLAIMS UNDER REVIEW ---", 1)[1]
            claims = json.loads(tail[tail.index("[") :].strip())
            refuted = scenario.startswith("refuted")
            payload = {
                "verdicts": [
                    {
                        "claim_id": claim["id"],
                        "verdict": "refuted" if refuted else "upheld",
                        "confidence": "high",
                        "evidence_assessment": "disputed" if refuted else "confirmed",
                        "reasoning": "The cited contract has no validation guard.",
                        "counter_evidence": "spec.md:2 requires validation" if refuted else None,
                        "amended_claim": None,
                    }
                    for claim in claims
                ]
            }
        elif scenario.startswith("clean"):
            payload = {"no_findings": True}
        else:
            # Each model identifies a distinct defect; identical subsequent
            # critiques let the real ledger exercise alias/deduplication.
            suffix = ""
            if scenario.startswith("new"):
                suffix = Path.cwd().parent.name
            payload = {
                "findings": [
                    {
                        "severity": "high",
                        "claim": f"Missing guard {scenario}{suffix}",
                        "location": f"spec.md:{scenario}{suffix}",
                        "evidence": "spec.md:2",
                        "failure_scenario": f"Unchecked request {scenario}{suffix} reaches the handler",
                        "suggested_fix": "Validate input before dispatch.",
                    }
                ]
            }
        msg = message(payload, stop="aborted" if scenario.startswith("aborted") else "stop")
    emit({"type": "agent_end", "messages": [msg], "willRetry": False})
    emit({"type": "agent_settled", "aborted": scenario.startswith("aborted")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
