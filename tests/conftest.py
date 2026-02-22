import os
import sys
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
SRC_PATH = os.path.join(REPO_ROOT, "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)


@pytest.fixture
def workspace_id(tmp_path):
    """Provide a fresh temporary workspace directory for each test.

    Uses pytest's tmp_path so every test gets an isolated, empty directory
    with no pre-existing database, avoiding migration conflicts.
    """
    ws = str(tmp_path)
    yield ws
    # Clean up the cached DB connection after each test so the connection
    # pool doesn't leak between tests or sessions.
    try:
        from engrams.db.database import close_db_connection
        close_db_connection(ws)
    except Exception:
        pass


@pytest.fixture
def workspace_path(tmp_path):
    """Provide a fresh temporary workspace with an initialised Engrams DB.

    Used by tests that open the database via EngramsReader (which requires the
    DB to already exist).  The fixture boots the DB via get_db_connection and
    then closes the write connection so the reader can open it read-only.
    """
    ws = str(tmp_path)
    # Initialise the schema by obtaining (and then releasing) a write connection.
    try:
        from engrams.db.database import get_db_connection, close_db_connection
        get_db_connection(ws)
        close_db_connection(ws)
    except Exception:
        pass
    yield ws
    # Best-effort cleanup.
    try:
        from engrams.db.database import close_db_connection
        close_db_connection(ws)
    except Exception:
        pass
