import pytest
from pydantic import SecretStr

from app.domain.errors import LlmUnavailableError
from app.infrastructure.anthropic_llm import AnthropicLlm
from app.infrastructure.scripted_llm import DemoLlm
from app.infrastructure.unavailable_llm import UnavailableLlm
from app.main import build_llm
from app.settings import Settings


def settings(tmp_path, **kwargs):
    return Settings(database_path=tmp_path / "x.sqlite", **kwargs)


def test_the_provider_setting_chooses_the_gateway(tmp_path):
    assert isinstance(build_llm(config=settings(tmp_path)), UnavailableLlm)
    assert isinstance(build_llm(config=settings(tmp_path, llm_provider="scripted")), DemoLlm)
    keyed = settings(tmp_path, llm_provider="anthropic", anthropic_api_key=SecretStr("sk-x"))
    assert isinstance(build_llm(config=keyed), AnthropicLlm)


def test_the_anthropic_provider_without_a_key_says_which_variable_to_set(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    gateway = build_llm(config=settings(tmp_path, llm_provider="anthropic"))
    with pytest.raises(LlmUnavailableError, match="PNVERIF_ANTHROPIC_API_KEY"):
        gateway.next_step(system="", messages=(), tools=())


def test_the_key_can_come_from_the_usual_variable_and_is_never_printed(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    config = settings(tmp_path)
    assert config.anthropic_api_key.get_secret_value() == "sk-secret"
    assert "sk-secret" not in repr(config)
