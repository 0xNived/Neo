from neo.domain.models import Session
from neo.memory.sqlite_sessions import SqliteSessionStore


async def test_session_title_can_be_renamed_and_persists(tmp_path):
    store = SqliteSessionStore(tmp_path / "neo.sqlite3")
    await store.initialize()
    session = Session(
        "session-1",
        "Owner",
        [{"role": "user", "content": "Original first message"}],
    )
    await store.save(session)

    assert await store.rename("session-1", "Owner", "Project planning")
    sessions = await store.list_for_user("Owner")

    assert sessions[0]["title"] == "Project planning"
