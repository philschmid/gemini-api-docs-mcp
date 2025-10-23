import os
from pathlib import Path

def get_db_path() -> str:
    """
    Determines the database path.
    Prioritizes GEMINI_DOCS_DB_PATH environment variable.
    Defaults to ~/.mcp/gemini-api-docs/database.db.
    Ensures the parent directory exists.
    """
    env_path = os.environ.get("GEMINI_DOCS_DB_PATH")
    if env_path:
        db_path = Path(env_path)
    else:
        db_path = Path.home() / ".mcp" / "gemini-api-docs" / "database.db"
    
    # Ensure directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    return str(db_path)

DB_PATH = get_db_path()
