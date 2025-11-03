# Use Python 3.11 slim image for smaller footprint
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install uv for faster dependency management (optional but recommended)
# If you prefer pip, you can skip this and use pip install instead
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml uv.lock* README.md ./
COPY gemini_docs_mcp ./gemini_docs_mcp

# Install dependencies using uv
# This creates a virtual environment and installs all dependencies
RUN uv sync --frozen --no-dev

# Set environment variable for database path (can be overridden)
ENV GEMINI_DOCS_DB_PATH=/data/database.db

# Create data directory for database
RUN mkdir -p /data

# Set the entrypoint to run the MCP server
# Using uv run to execute within the virtual environment
ENTRYPOINT ["uv", "run", "gemini-docs-mcp"]
