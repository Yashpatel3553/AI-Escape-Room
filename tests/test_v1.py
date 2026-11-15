"""Light tests for V1 plumbing (the LLM itself is mocked)."""
import v1.game as game


def test_escape_token_is_detected_and_hidden(monkeypatch):
    monkeypatch.setattr(game, "generate", lambda *a, **k: "The door swings open. " + game.ESCAPE_TOKEN)
    s = game.GameSession()
    reply = s.send("enter the code")
    assert s.escaped is True
    assert game.ESCAPE_TOKEN not in reply


def test_history_is_kept_and_restart_clears_it(monkeypatch):
    monkeypatch.setattr(game, "generate", lambda *a, **k: "You see dust.")
    s = game.GameSession()
    s.send("look")
    assert [m["role"] for m in s.history] == ["user", "assistant", "user", "assistant"]
    s.reset()
    assert len(s.history) == 2 and s.escaped is False


def test_failed_call_does_not_corrupt_history(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("quota")

    monkeypatch.setattr(game, "generate", boom)
    s = game.GameSession()
    try:
        s.send("look")
    except RuntimeError:
        pass
    assert len(s.history) == 2


def test_v1_prompt_contains_the_secrets_by_design():
    # Documents the V1 weakness that V2 removes: solutions live inside the prompt.
    assert "3142" in game.SYSTEM_PROMPT and "9026" in game.SYSTEM_PROMPT
