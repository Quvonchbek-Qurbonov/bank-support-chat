from __future__ import annotations

import threading
import time
from collections import OrderedDict

# In-memory only, by design: no auth, no persistence requirement, history
# just needs to survive for the lifetime of one browser tab. A page reload
# gets a brand new session_id from the frontend, so old entries here become
# orphaned and are swept up by the caps below rather than explicitly deleted.
#
# Caveat: this only works because the api service runs a single uvicorn
# worker/process (see docker-compose.yml: `uvicorn app.main:app`, no
# --workers flag). If that ever changes, or the api service is scaled to
# multiple replicas, this dict stops being shared across requests and you'd
# need Redis or similar instead.

MAX_SESSIONS = 1000                 # hard cap on concurrent sessions kept in memory
MAX_TURNS_PER_SESSION = 6           # 6 messages = 3 user/assistant exchanges
SESSION_TTL_SECONDS = 60 * 60       # idle sessions older than this are dropped

_lock = threading.Lock()
_sessions: "OrderedDict[str, dict]" = OrderedDict()


def _evict_locked() -> None:
    now = time.time()
    stale_ids = [
        sid for sid, session in _sessions.items()
        if now - session["updated_at"] > SESSION_TTL_SECONDS
    ]
    for sid in stale_ids:
        _sessions.pop(sid, None)

    while len(_sessions) > MAX_SESSIONS:
        _sessions.popitem(last=False)  # drop least-recently-used


def get_history(session_id: str) -> list[dict]:
    """Return the stored [{"role": ..., "content": ...}, ...] turns, oldest first."""
    with _lock:
        session = _sessions.get(session_id)
        if not session:
            return []
        _sessions.move_to_end(session_id)
        return list(session["messages"])


def append_turn(session_id: str, question: str, answer: str) -> None:
    with _lock:
        session = _sessions.setdefault(
            session_id, {"messages": [], "updated_at": time.time()}
        )
        session["messages"].append({"role": "user", "content": question})
        session["messages"].append({"role": "assistant", "content": answer})
        session["messages"] = session["messages"][-MAX_TURNS_PER_SESSION:]
        session["updated_at"] = time.time()
        _sessions.move_to_end(session_id)
        _evict_locked()


def clear_session(session_id: str) -> None:
    with _lock:
        _sessions.pop(session_id, None)