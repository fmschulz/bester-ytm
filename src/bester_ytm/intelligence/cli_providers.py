"""Run Codex and Claude CLI requests with cancellation and timeout handling."""

from __future__ import annotations

import json
import shutil
import subprocess
from threading import Event

from .cli_process import CliCancelledError, run_cli
from .settings import IntelligenceError, IntelligenceSettings

CODEX_TIMEOUT_SECONDS = 180.0

CLAUDE_TIMEOUT_SECONDS = 180.0

CODEX_MUSIC_INSTRUCTIONS = (
    "This is a one-shot request for a music player, not a coding task. "
    "Return only the JSON requested in the prompt. Do not inspect local files, "
    "run shell commands, invoke skills, or perform agent/session setup or reporting. "
    "Use web search only when needed to find a radio station's current stream URL."
)


def codex_text(settings: IntelligenceSettings, prompt: str, *, cancel: Event | None = None) -> str:
    """Raw codex exec output for a prompt; raises IntelligenceError."""
    codex = shutil.which("codex")
    if not codex:
        raise IntelligenceError("codex CLI is not installed or not on PATH")
    cmd = [
        codex,
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "-c",
        'model_reasoning_effort="medium"',
        "-c",
        "skills.include_instructions=false",
        "-c",
        f"developer_instructions={json.dumps(CODEX_MUSIC_INSTRUCTIONS)}",
    ]
    if settings.model:
        cmd += ["-m", settings.model]
    cmd.append(prompt)
    try:
        result = run_cli(cmd, timeout=CODEX_TIMEOUT_SECONDS, cancel=cancel)
    except (CliCancelledError, OSError) as exc:
        raise IntelligenceError(str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise IntelligenceError(
            f"codex did not answer within {int(CODEX_TIMEOUT_SECONDS)}s"
        ) from exc
    if result.returncode != 0:
        raise IntelligenceError(
            f"codex exec failed (exit {result.returncode}): {_stderr_summary(result.stderr)}"
        )
    return result.stdout


def claude_text(
    settings: IntelligenceSettings,
    prompt: str,
    *,
    web_access: bool = False,
    cancel: Event | None = None,
) -> str:
    """Raw claude -p output for a prompt; raises IntelligenceError.

    Uses the Claude Code CLI print mode, riding the user's existing claude
    login without user settings or tools beyond the requested web access.
    """
    claude = shutil.which("claude")
    if not claude:
        raise IntelligenceError("claude CLI is not installed or not on PATH")
    cmd = [claude, "-p", "--output-format", "text", "--setting-sources", "", "--tools"]
    cmd.append("WebSearch,WebFetch" if web_access else "")
    if web_access:
        cmd += ["--allowedTools", "WebSearch,WebFetch"]
    cmd += ["--disable-slash-commands", "--strict-mcp-config"]
    if settings.model:
        cmd += ["--model", settings.model]
    cmd.append(prompt)
    try:
        result = run_cli(cmd, timeout=CLAUDE_TIMEOUT_SECONDS, cancel=cancel)
    except (CliCancelledError, OSError) as exc:
        raise IntelligenceError(str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise IntelligenceError(
            f"claude did not answer within {int(CLAUDE_TIMEOUT_SECONDS)}s"
        ) from exc
    if result.returncode != 0:
        raise IntelligenceError(
            f"claude -p failed (exit {result.returncode}): {_stderr_summary(result.stderr)}"
        )
    return result.stdout


def _stderr_summary(stderr: str) -> str:
    """The decisive error is printed last; startup log noise comes first."""
    lines = [line.strip() for line in stderr.strip().splitlines() if line.strip()]
    if not lines:
        return "no error output"
    errors = [line for line in lines if "ERROR" in line]
    return (errors[-1] if errors else lines[-1])[:300]
