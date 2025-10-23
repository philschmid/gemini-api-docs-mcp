from sqlite_utils import Database
import sys

DB_PATH = "database.db"

def test_search(query: str):
    """Tests FTS search for a given query."""
    print(f"\n--- Testing search for: '{query}' ---")
    try:
        db = Database(DB_PATH)
        if "docs" not in db.table_names():
             print("Error: 'docs' table not found. Has ingestion run?")
             return

        results = list(db["docs"].search(query, limit=5))
        
        if not results:
            print("No results found.")
            return

        print(f"Found {len(results)} results (showing top 5):")
        for i, r in enumerate(results, 1):
            print(f"\nResult {i}:")
            print(f"Title: {r['title']}")
            print(f"URL: {r['url']}")
            snippet = r['content'][:200].replace('\n', ' ') + "..."
            print(f"Snippet: {snippet}")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        for query in sys.argv[1:]:
            test_search(query)
    else:
        # Default test queries if none provided
        test_search("embeddings")
        test_search("gemini pro")
        test_search("api key")
