import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import List, Tuple
import httpx
from bs4 import BeautifulSoup
from sqlite_utils import Database
from .config import DB_PATH

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

LLMS_TXT_URL = "https://ai.google.dev/gemini-api/docs/llms.txt"
MAX_CONCURRENT_REQUESTS = 20

async def fetch_url(client: httpx.AsyncClient, url: str) -> str:
    """Fetches content from a URL and extracts text from HTML."""
    try:
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()
        
        # Use BeautifulSoup to extract text if it's HTML
        if "text/html" in response.headers.get("content-type", ""):
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Remove script and style elements
            for script_or_style in soup(["script", "style", "header", "footer", "nav"]):
                script_or_style.decompose()
                
            text = soup.get_text(separator='\n')
            
            # Break into lines and remove leading/trailing space on each
            lines = (line.strip() for line in text.splitlines())
            # Break multi-headlines into a line each
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            # Drop blank lines
            text = '\n'.join(chunk for chunk in chunks if chunk)
            return text
            
        return response.text
    except httpx.HTTPError as e:
        logger.error(f"Error fetching {url}: {e}")
        return ""
    except Exception as e:
        logger.error(f"Error parsing {url}: {e}")
        return ""

def parse_llms_txt(content: str) -> List[Tuple[str, str]]:
    """Parses llms.txt content to extract titles and URLs."""
    links = []
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("- [") and "](" in line and ")" in line:
            try:
                title_part, url_part = line.split("](", 1)
                title = title_part[3:].strip()
                url = url_part.split(")")[0].strip()
                links.append((title, url))
            except ValueError:
                logger.warning(f"Could not parse line: {line}")
    
    return links

def get_content_hash(content: str) -> str:
    """Calculates SHA256 hash of content."""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()

async def process_link(client: httpx.AsyncClient, db: Database, title: str, url: str, semaphore: asyncio.Semaphore):
    """Processes a single link: fetch, hash, and upsert if changed."""
    async with semaphore:
        # Check if update is needed
        current_hash = None
        try:
            row = db["docs"].get(url)
            current_hash = row["content_hash"]
        except Exception: # Row not found
            pass

        content = await fetch_url(client, url)
        if not content:
            return

        new_hash = get_content_hash(content)

        if new_hash != current_hash:
            logger.info(f"Updating {url}")
            db["docs"].upsert({
                "url": url.replace(".md.txt", ""),
                "title": title,
                "content": content,
                "content_hash": new_hash,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }, pk="url")
        else:
            logger.debug(f"No changes for {url}")

async def ingest_docs():
    """Main ingestion function to be called on server startup."""
    logger.info("Starting documentation ingestion...")
    db = Database(DB_PATH)
    
    # Ensure table exists with FTS
    if "docs" not in db.table_names():
        db["docs"].create({
            "url": str,
            "title": str,
            "content": str,
            "content_hash": str,
            "last_updated": str,
        }, pk="url")
        db["docs"].enable_fts(["title", "content"], create_triggers=True, tokenize="trigram")

    async with httpx.AsyncClient() as client:
        llms_txt_content = await fetch_url(client, LLMS_TXT_URL)
        if not llms_txt_content:
            logger.error("Failed to fetch llms.txt. Aborting ingestion.")
            return

        links = parse_llms_txt(llms_txt_content)
        logger.info(f"Found {len(links)} links in llms.txt")

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        tasks = [process_link(client, db, title, url, semaphore) for title, url in links]
        await asyncio.gather(*tasks)

    logger.info("Documentation ingestion complete.")

if __name__ == "__main__":
    asyncio.run(ingest_docs())
