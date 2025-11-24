import os
from pathlib import Path

def get_db_path() -> str:
    """
    Determines the database path.
    Prioritizes GEMINI_DOCS_DB_PATH environment variable.
    For containerized environments, defaults to /tmp/gemini-api-docs/database.db.
    For local environments, defaults to ~/.mcp/gemini-api-docs/database.db.
    Ensures the parent directory exists.
    """
    env_path = os.environ.get("GEMINI_DOCS_DB_PATH")
    if env_path:
        db_path = Path(env_path)
    else:
        # Use /tmp in containerized environments (when HOME might not be writable)
        # Check if we're in a container by checking for /.dockerenv or K_SERVICE (Cloud Run)
        if os.path.exists("/.dockerenv") or os.environ.get("K_SERVICE") or os.environ.get("CONTAINER") == "true":
            db_path = Path("/tmp") / "gemini-api-docs" / "database.db"
        else:
            db_path = Path.home() / ".mcp" / "gemini-api-docs" / "database.db"
    
    # Ensure directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    return str(db_path)

DB_PATH = get_db_path()
