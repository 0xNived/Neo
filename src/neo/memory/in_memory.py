from ..domain.models import Session


class InMemorySessionStore:
    def __init__(self):
        self._sessions: dict[str, Session] = {}

    async def get_or_create(self, session_id: str, user_id: str) -> Session:
        session = self._sessions.setdefault(session_id, Session(session_id, user_id))
        if session.user_id != user_id:
            raise PermissionError("Session belongs to another user")
        return session
