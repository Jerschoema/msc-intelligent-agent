from src.config.settings import Settings


def test_defaults_present():
    s = Settings()
    assert s.ollama_model == "qwen3:4b"
    assert s.max_loops == 5
    assert s.agent_max_steps == 12
    assert s.top_k == 4


def test_env_override_is_picked_up(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("TOP_K", "8")
    s = Settings()
    assert s.ollama_model == "qwen3:8b"
    assert s.top_k == 8


def test_bad_int_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("TOP_K", "not-a-number")
    s = Settings()
    assert s.top_k == 4


def test_deep_mode_raises_the_budgets_but_keeps_them_finite(monkeypatch):
    import src.config.settings as settings_mod
    monkeypatch.setattr(settings_mod, "settings", Settings())
    settings_mod.enable_deep_mode()
    s = settings_mod.settings
    assert s.search_max_results > 5 and s.max_loops > 5
    assert s.agent_max_steps <= 50 and s.max_loops <= 20
