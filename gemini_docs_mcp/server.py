import os
import logging
from fastmcp import FastMCP
from contextlib import asynccontextmanager
import asyncio
from .ingest import ingest_docs
from sqlite_utils import Database
from pydantic import Field
from typing import List
from .config import DB_PATH
from typing import Annotated

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@asynccontextmanager
async def server_lifespan(server: FastMCP):
    """Lifespan context manager for the FastMCP server."""
    logger.info("Server starting up...")
    logger.info(f"Database path: {DB_PATH}")
    
    # Ensure database directory exists
    from pathlib import Path
    db_path_obj = Path(DB_PATH)
    db_path_obj.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Database directory ready: {db_path_obj.parent}")
    
    # Run ingestion in background so the server can start quickly (important for Cloud Run)
    # Don't block startup if ingestion fails - server should be usable even without fresh data
    async def run_ingestion_safely():
        try:
            logger.info("Starting background documentation ingestion...")
            await ingest_docs()
            logger.info("Documentation ingestion completed")
        except Exception as e:
            logger.error(f"Ingestion failed (server will continue): {e}", exc_info=True)
    
    # Start ingestion in background without blocking
    asyncio.create_task(run_ingestion_safely())
    logger.info("Server ready, ingestion running in background")
    yield
    logger.info("Server shutting down...")

def sanitize_term(query):
    """
    Fixes 'syntax error near "."' by wrapping terms with dots in double quotes.
    For standard FTS5 (even with trigram), "2.5" is treated as a valid phrase,
    whereas 2.5 raw is treated as broken syntax.
    """
    terms = query.split()
    sanitized = []
    for term in terms:
        # If the term contains a dot, it MUST be quoted to pass the FTS5 parser.
        # We also escape any existing double quotes by doubling them (" -> "")
        if '.' in term:
            safe_term = term.replace('"', '""')
            sanitized.append(f'"{safe_term}"')
        else:
            sanitized.append(term)
    
    return " ".join(sanitized)

# Initialize FastMCP server with lifespan
mcp = FastMCP("Gemini API Docs", lifespan=server_lifespan)
DB_TOP_K = 3

@mcp.tool(
    name="search_documentation",
    description="""Performs a standard keyword search on Gemini API documentation.
CRITICAL: This is a naive keyword search, NOT semantic. Long queries will FAIL.
You MUST use VERY SHORT keyword based queries (max 1-3 keywords) focusing only on the most unique terms.
Break complex questions into separate, simple queries. It will return the full documentation page for a capability or feature."""
)
def search_documentation(queries: Annotated[
        List[str],
        Field(
            description="""List of up to 3 SHORT keyword queries. Keep each query under 3 words.
BAD: 'google genai python generate image save bytes' (too specific, will fail).
GOOD: ['function calling', 'imagen parameters', 'save bytes'] (broad, likely to hit)."""
        ),
    ]) -> str:
    """Performs a full-text search on Gemini documentation for the given queries. Optimize queries for Full Text Searches."""
    db = Database(DB_PATH)
    
    # Combine optimized queries with OR (if multiple original queries were provided)
    safe_queries = [sanitize_term(q) for q in queries]
    combined_query = " OR ".join(f"({q})" for q in safe_queries)
    print(f"Combined query: {combined_query}")

    
    results = list(db["docs"].search(combined_query, limit=DB_TOP_K))
    
    if not results:
        return "No matching documentation found."

    formatted_results = []
    for r in results:
        formatted_results.append(f"# [{r['title']}]({r['url']})\n{r['content']}\n")
    
    final_content = """[!WARNING]
SDKs: The @google/generative-ai (JavaScript) and google-generativeai (Python) SDKs are legacy. Please migrate to the new @google/genai (JavaScript) and google-genai (Python) SDKs.
Models: Gemini-1.5 to gemini-2.0 are old legacy models. Use the newer models available."""

    return final_content + "\n\n---\n\n".join(formatted_results)

@mcp.tool(
    name="get_capability_page",
    description="""Retrieves the full content of a specific documentation page by its exact title.
You can call can this tool WITHOUT arguments first to see a master list of all available page titles.
Then, call it again with the exact title you need.""",
)
def get_capability_page(capability: Annotated[
        str,
        Field(
            description="The EXACT title of the documentation page to retrieve (case-sensitive). If you do not know the exact title, OMIT this argument to receive a master list of all available titles.",
        ),
    ]) -> str:
    """
    Returns documentation for a specific capability, or a list of available capabilities.
    """
    db = Database(DB_PATH)
    
    if capability:
        try:
            # Search by title. Since title isn't PK, we use a query.
            # Assuming titles are unique enough for this purpose.
            rows = list(db.query("SELECT content FROM docs WHERE title = ?", [capability]))
            if rows:
                return rows[0]["content"]
            else:
                return f"Capability '{capability}' not found."
        except Exception as e:
            return f"Error retrieving capability: {e}"
    else:
        # Return list of all titles
        titles = [row["title"] for row in db.query("SELECT title FROM docs ORDER BY title")]
        return "Available Capabilities:\n" + "\n".join([f"- {t}" for t in titles])

@mcp.tool(
    name="get_current_model",
    description="Shortcut tool to explicitly retrieve the canonical 'Gemini Models' documentation page. Use this to fast-track finding details about available model variants (Pro, Flash, etc.), their capabilities, versioning, and context window sizes.",
)
def get_current_model() -> str:
    """Returns documentation for current Gemini models."""
    db = Database(DB_PATH)
    # We need to find the models page. Based on previous research it might contain "Gemini Models" in title.
    # Let's try to find it dynamically or hardcode if we are sure.
    # For now, let's search for a likely title.
    try:
        rows = list(db.query("SELECT content FROM docs WHERE title LIKE '%Gemini Models%' LIMIT 1"))
        if rows:
            return rows[0]["content"]
        
        # Fallback: try to find by URL if we know it
        rows = list(db.query("SELECT content FROM docs WHERE url LIKE '%/models%' LIMIT 1"))
        if rows:
             return rows[0]["content"]
             
        return "Gemini Models documentation page not found."
    except Exception as e:
        return f"Error retrieving models documentation: {e}"

def main():
    # If PORT is set, run as HTTP server (for Cloud Run)
    # Otherwise, run in stdio mode (for local MCP clients)
    if os.environ.get("PORT"):
        port = int(os.environ.get("PORT", "8080"))
        host = "0.0.0.0"

        logger.info(f"Starting MCP server in HTTP mode on {host}:{port}")
        logger.info(f"MCP endpoint will be available at http://{host}:{port}/mcp")

        # FastMCP exposes HTTP apps via http_app or streamable_http_app attributes
        # Use streamable_http_app for SSE transport (better for remote clients like Cursor)
        mcp_app = None
        
        if hasattr(mcp, "streamable_http_app"):
            mcp_app = mcp.streamable_http_app
            logger.info(f"Found mcp.streamable_http_app: {type(mcp_app)}")
        elif hasattr(mcp, "http_app"):
            mcp_app = mcp.http_app
            logger.info(f"Found mcp.http_app: {type(mcp_app)}")
        
        if mcp_app is not None:
            import uvicorn
            logger.info(f"Starting uvicorn with HTTP app type: {type(mcp_app)}")
            try:
                # Configure uvicorn for Cloud Run
                config = uvicorn.Config(
                    mcp_app,
                    host=host,
                    port=port,
                    log_level="info",
                    access_log=True,
                    reload=False,
                )
                server = uvicorn.Server(config)
                logger.info(f"Uvicorn server configured, starting on {host}:{port}")
                server.run()
                return
            except Exception as e:
                logger.error(f"Failed to start uvicorn: {e}", exc_info=True)
                raise

        # Fallback: try FastMCP's HTTP run methods
        logger.info("Trying FastMCP HTTP run methods...")
        try:
            # Try run_http_async if available
            if hasattr(mcp, "run_http_async"):
                import asyncio
                logger.info("Using run_http_async")
                asyncio.run(mcp.run_http_async(host=host, port=port))
                return
        except Exception as e:
            logger.warning(f"run_http_async failed: {e}")
        
        # Last resort: this shouldn't happen if FastMCP is properly installed
        raise RuntimeError(
            f"Failed to start MCP HTTP server. FastMCP object type: {type(mcp)}. "
            f"Available HTTP attributes: http_app={hasattr(mcp, 'http_app')}, "
            f"streamable_http_app={hasattr(mcp, 'streamable_http_app')}, "
            f"run_http_async={hasattr(mcp, 'run_http_async')}"
        )
    else:
        # Run in stdio mode (for local MCP clients)
        logger.info("Starting MCP server in stdio mode")
        try:
            # FastMCP's run() method defaults to stdio when no host/port is provided
            mcp.run()
        except Exception as e:
            logger.error(f"Failed to start MCP stdio server: {e}", exc_info=True)
            raise

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import sys
        import traceback
        logger.error(f"Fatal error starting server: {e}", exc_info=True)
        print(f"Fatal error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
