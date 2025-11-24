FROM python:3.11-slim

WORKDIR /app

# Install system dependencies needed for building packages and SQLite
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md /app/
COPY gemini_docs_mcp /app/gemini_docs_mcp

# Install the package and dependencies
RUN pip install --upgrade pip
RUN pip install .

# Cloud Run uses the PORT environment variable; default to 8080
ENV PORT 8080

# Ensure database directory exists and is writable
RUN mkdir -p /tmp/gemini-api-docs && chmod 777 /tmp/gemini-api-docs

EXPOSE 8080

# Run the MCP server module
CMD ["python", "-m", "gemini_docs_mcp.server"]
