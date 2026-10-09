from neo.brain.prompt_builder import PromptBuilder
from neo.brain.response_validator import validate_reply
from neo.persona.profile import Persona


def test_prompt_keeps_neo_identity():
    assert "You are Neo" in PromptBuilder("Nico", "Asia/Calcutta", Persona()).build(
        [], []
    )


def test_rejects_provider_identity_leak():
    assert (
        validate_reply({"kind": "message", "content": "I'm Dots, an AI model."}, set())[
            "content"
        ]
        == "I'm Neo, your personal assistant."
    )
