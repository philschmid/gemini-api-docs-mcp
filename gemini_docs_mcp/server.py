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
    description="""Performs a keyword-based full-text search on Gemini documentation.
IMPORTANT: This uses standard text matching, NOT semantic search.
To ensure results, you MUST optimize queries by removing stop words (e.g., 'with', 'the', 'in', 'how to') and focusing ONLY on core nouns and verbs.
If a query fails, try simpler synonyms or root words."""
)
def search_documentation(queries: Annotated[
        List[str],
        Field(
            description="""List of up to 3 optimized keyword queries.
Good examples: ['function calling', 'gemini 2.5', 'function declarations'].
Bad example: ['how do I do function calling with gemini?']"""
        ),
    ]) -> str:
    """Performs a full-text search on Gemini documentation for the given queries. Optimize queries for Full Text Searches."""
    db = Database(DB_PATH)
    
    # optimized_queries = []
    # for q in queries:
    #     words = q.lower().split()
    #     optimized_q = " AND ".join(f"{w}*" for w in filtered_words)
    #     optimized_queries.append(optimized_q)
    # print(f"Optimized queries: {optimized_queries}")

    # Combine optimized queries with OR (if multiple original queries were provided)
    combined_query = " OR ".join(f"({q})" for q in queries)
    print(f"Combined query: {combined_query}")

    
    results = list(db["docs"].search(combined_query, limit=DB_TOP_K))
    
    if not results:
        return "No matching documentation found."

    formatted_results = []
    for r in results:
        formatted_results.append(f"# [{r['title']}]({r['url']})\n{r['content']}")
    
    return "\n\n---\n\n".join(formatted_results)

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
    mcp.run()

if __name__ == "__main__":
    main()
