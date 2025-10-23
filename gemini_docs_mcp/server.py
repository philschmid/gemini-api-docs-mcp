from fastmcp import FastMCP
from contextlib import asynccontextmanager
from .ingest import ingest_docs
from sqlite_utils import Database
from pydantic import Field
from typing import List
from .config import DB_PATH
from typing import Annotated

@asynccontextmanager
async def server_lifespan(server: FastMCP):
    """Lifespan context manager for the FastMCP server."""
    await ingest_docs()
    yield

# Initialize FastMCP server with lifespan
mcp = FastMCP("Gemini API Docs", lifespan=server_lifespan)

DB_TOP_K = 3

@mcp.tool(
    name="search_documentation",
    description="Performs a full-text search on Gemini documentation for the given queries. Optimize queries for Full Text Searches.",
)
def search_documentation(queries: Annotated[
        List[str],
        Field(
            description="List of up to 3 search queries."
        ),
    ]) -> str:
    """Performs a full-text search on Gemini documentation for the given queries. Optimize queries for Full Text Searches."""
    db = Database(DB_PATH)
    
    # Combine queries with OR for FTS
    combined_query = " OR ".join(f'"{q}"' for q in queries)
    
    results = list(db["docs"].search(combined_query, limit=DB_TOP_K))
    
    if not results:
        return "No matching documentation found."

    formatted_results = []
    for r in results:
        formatted_results.append(f"# [{r['title']}]({r['url']})\n{r['content']}")
    
    return "\n\n---\n\n".join(formatted_results)

@mcp.tool(
    name="get_capability_page",
    description="Returns documentation for a specific capability, or a list of available capabilities.",
)
def get_capability_page(capability: Annotated[
        str,
        Field(
            description="The title of the capability/page to retrieve. If None, returns a list of all available capabilities.",
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
    description="Returns documentation for current Gemini models. This includes the latest and available models.",
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
    mcp.run()

if __name__ == "__main__":
    main()
