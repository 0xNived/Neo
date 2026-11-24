from types import SimpleNamespace

from neo.brain.providers import OpenAICompatibleBrain, build_brain


def test_generic_openai_compatible_provider_uses_portable_settings():
    settings = SimpleNamespace(
        owner_name="Owner",
        owner_timezone="UTC",
        llm_provider="openai_compatible",
        llm_model="example-model",
        llm_base_url="https://gateway.example/v1",
        llm_api_key="example-key",
    )

    brain = build_brain(settings)

    assert isinstance(brain, OpenAICompatibleBrain)
    assert brain.base_url == "https://gateway.example/v1"
    assert brain.model == "example-model"
