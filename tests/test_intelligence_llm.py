from __future__ import annotations

import subprocess
from types import SimpleNamespace

import anthropic
import pytest

from bester_ytm.intelligence import llm
from bester_ytm.intelligence.llm import (
    IntelligenceError,
    IntelligenceSettings,
    SuggestedTrack,
    SuggestedTracks,
    build_prompt,
    resolve_provider,
    suggest_playlist,
    suggest_tracks,
)

TRACKS_JSON = (
    '[{"artist": "Machine Head", "title": "Davidian", "reason": "groove metal"},'
    ' {"artist": "Prong", "title": "Snap Your Fingers", "reason": "tight groove"}]'
)


def test_resolve_provider_auto_prefers_codex_when_installed(monkeypatch) -> None:
    monkeypatch.setattr(llm.shutil, "which", lambda name: "/usr/bin/codex")
    assert resolve_provider(IntelligenceSettings()) == "codex"

    monkeypatch.setattr(llm.shutil, "which", lambda name: None)
    assert resolve_provider(IntelligenceSettings()) == "heuristic"


def test_resolve_provider_rejects_unknown_names() -> None:
    with pytest.raises(IntelligenceError, match="unknown intelligence provider"):
        resolve_provider(IntelligenceSettings(provider="gpt"))


def test_heuristic_provider_has_no_ai_suggestions(monkeypatch) -> None:
    with pytest.raises(IntelligenceError, match="configure \\[intelligence\\]"):
        suggest_tracks(IntelligenceSettings(provider="heuristic"), [], 3)


def test_prompt_includes_queue_brief_and_json_contract() -> None:
    prompt = build_prompt(["Sepultura - Territory"], 4, "more tribal")

    assert "exactly 4 songs" in prompt
    assert "- Sepultura - Territory" in prompt
    assert "Listener brief: more tribal" in prompt
    assert '"artist"' in prompt and "JSON object" in prompt
    assert '"name"' in prompt and "use exactly that as the playlist name" in prompt


def test_codex_provider_parses_final_json_line(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        stdout = (
            f"session id: abc\nuser\nprompt echo\ncodex\n{TRACKS_JSON}\n"
            f"tokens used\n9,000\n{TRACKS_JSON}\n"
        )
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(llm.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(llm.subprocess, "run", fake_run)

    tracks = suggest_tracks(IntelligenceSettings(provider="codex"), ["A - B"], 2)

    assert [track.artist for track in tracks] == ["Machine Head", "Prong"]
    assert "--skip-git-repo-check" in calls[0]
    assert "--sandbox" in calls[0] and "read-only" in calls[0]


def test_codex_provider_parses_named_playlist_object(monkeypatch) -> None:
    stdout = (
        'session id: abc\n{"name": "powermetal-10", "tracks": '
        '[{"artist": "Blind Guardian", "title": "Valhalla", "reason": "anthem"}]}\n'
        "tokens used\n9,000\n"
    )
    monkeypatch.setattr(llm.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(
        llm.subprocess,
        "run",
        lambda cmd, **kwargs: SimpleNamespace(returncode=0, stdout=stdout, stderr=""),
    )

    playlist = suggest_playlist(IntelligenceSettings(provider="codex"), [], 1)

    assert playlist.name == "powermetal-10"
    assert [track.title for track in playlist.tracks] == ["Valhalla"]


def test_codex_provider_reports_failure_and_timeout(monkeypatch) -> None:
    monkeypatch.setattr(llm.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(
        llm.subprocess,
        "run",
        lambda cmd, **kwargs: SimpleNamespace(returncode=2, stdout="", stderr="login required"),
    )
    with pytest.raises(IntelligenceError, match="codex exec failed.*login required"):
        suggest_tracks(IntelligenceSettings(provider="codex"), [], 2)

    def fake_timeout(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, timeout=1)

    monkeypatch.setattr(llm.subprocess, "run", fake_timeout)
    with pytest.raises(IntelligenceError, match="did not answer"):
        suggest_tracks(IntelligenceSettings(provider="codex"), [], 2)


def test_codex_failure_surfaces_last_error_not_startup_noise(monkeypatch) -> None:
    stderr = (
        "Reading additional input from stdin...\n"
        "2026-06-11T21:06:19Z ERROR codex_core_skills::manager: failed to install "
        "system skills: io error while create system skills dir: File exists\n"
        "2026-06-11T21:06:20Z ERROR codex_login::auth::manager: Failed to refresh token\n"
        "ERROR: Your access token could not be refreshed. Please log out and sign in again.\n"
    )
    monkeypatch.setattr(llm.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(
        llm.subprocess,
        "run",
        lambda cmd, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr=stderr),
    )

    with pytest.raises(IntelligenceError, match="log out and sign in again"):
        suggest_tracks(IntelligenceSettings(provider="codex"), [], 2)


def test_stderr_summary_handles_empty_and_plain_output() -> None:
    assert llm._stderr_summary("") == "no error output"
    assert llm._stderr_summary("warming up\nconnection refused\n") == "connection refused"


def test_openai_provider_posts_to_compatible_endpoint(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update({"url": url, "json": json, "headers": headers})
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"choices": [{"message": {"content": f"```json\n{TRACKS_JSON}\n```"}}]},
        )

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(llm.requests, "post", fake_post)

    settings = IntelligenceSettings(provider="openai", model="meta-llama/llama-3-70b")
    tracks = suggest_tracks(settings, ["A - B"], 2)

    assert len(tracks) == 2
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"] == {"Authorization": "Bearer test-key"}
    assert captured["json"]["model"] == "meta-llama/llama-3-70b"


def test_openai_provider_requires_key_and_model(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(IntelligenceError, match="OPENROUTER_API_KEY is not set"):
        suggest_tracks(IntelligenceSettings(provider="openai", model="x"), [], 2)

    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    with pytest.raises(IntelligenceError, match="model must be set"):
        suggest_tracks(IntelligenceSettings(provider="openai"), [], 2)


def test_anthropic_provider_uses_structured_output(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeMessages:
        def parse(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                parsed_output=SuggestedTracks(
                    tracks=[SuggestedTrack(artist="Soulfly", title="Eye for an Eye")]
                )
            )

    monkeypatch.setattr(
        anthropic, "Anthropic", lambda: SimpleNamespace(messages=FakeMessages())
    )

    tracks = suggest_tracks(IntelligenceSettings(provider="anthropic"), ["A - B"], 1)

    assert tracks[0].artist == "Soulfly"
    assert captured["model"] == "claude-opus-4-8"
    assert captured["output_format"] is SuggestedTracks


def test_anthropic_provider_wraps_api_errors(monkeypatch) -> None:
    class FakeMessages:
        def parse(self, **kwargs):
            raise anthropic.AnthropicError("no api key")

    monkeypatch.setattr(
        anthropic, "Anthropic", lambda: SimpleNamespace(messages=FakeMessages())
    )

    with pytest.raises(IntelligenceError, match="Set ANTHROPIC_API_KEY"):
        suggest_tracks(IntelligenceSettings(provider="anthropic"), [], 1)


def test_parse_rejects_output_without_json(monkeypatch) -> None:
    monkeypatch.setattr(llm.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(
        llm.subprocess,
        "run",
        lambda cmd, **kwargs: SimpleNamespace(returncode=0, stdout="sorry, no idea", stderr=""),
    )
    with pytest.raises(IntelligenceError, match="returned no JSON track list"):
        suggest_tracks(IntelligenceSettings(provider="codex"), [], 2)


def test_resolve_provider_auto_falls_back_to_claude(monkeypatch) -> None:
    monkeypatch.setattr(
        llm.shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None
    )
    assert llm.resolve_provider(llm.IntelligenceSettings()) == "claude"


def test_claude_provider_parses_final_json_line(monkeypatch) -> None:
    payload = (
        '{"name": "Dub Classics", '
        '"tracks": [{"artist": "King Tubby", "title": "Dub Fi Gwan"}]}'
    )
    monkeypatch.setattr(llm.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(
        llm.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 0, stdout=f"Here you go:\n{payload}\n", stderr=""
        ),
    )

    result = llm.suggest_playlist(
        llm.IntelligenceSettings(provider="claude"), [], 1, "dub"
    )

    assert result.name == "Dub Classics"
    assert result.tracks[0].artist == "King Tubby"


def test_claude_provider_reports_failure(monkeypatch) -> None:
    monkeypatch.setattr(llm.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(
        llm.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 1, stdout="", stderr="Not logged in"
        ),
    )

    with pytest.raises(llm.IntelligenceError, match="claude -p failed"):
        llm.suggest_playlist(llm.IntelligenceSettings(provider="claude"), [], 1, "dub")
