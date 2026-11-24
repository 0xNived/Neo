from neo.configuration.settings import Settings
from neo.integrations.catalog import builtin_statuses


def test_catalog_reports_setup_without_leaking_credentials(tmp_path):
    settings = Settings(
        "test",
        8,
        False,
        "bot",
        "discord-secret",
        [],
        1,
        "telegram-secret",
        tmp_path / "telegram",
        "Owner",
        "Asia/Calcutta",
        None,
        90,
        tmp_path / "neo.sqlite3",
        "postgres://example",
        "ollama",
        "chat-model",
        "http://localhost:11434",
        "chat-secret",
        None,
        "ollama",
        "vision-model",
        "http://localhost:11434",
        "vision-secret",
        False,
        True,
        20,
    )

    statuses = {item.id: item.public() for item in builtin_statuses(settings)}

    assert statuses["discord_bot"]["state"] == "ready"
    assert statuses["telegram"]["state"] == "ready"
    assert statuses["vision"]["state"] == "disabled"
    assert statuses["browser"]["state"] == "needs_configuration"
    assert "secret" not in str(statuses)
