import asyncio
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def run():
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "gemini_docs_mcp.server"],
        env=None
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the connection
            await session.initialize()

            # List available tools
            tools = await session.list_tools()
            print("Available tools:", [tool.name for tool in tools.tools])

            # # Test get_capability (list)
            # result = await session.call_tool("get_capability_page", arguments={})
            # print("\nget_capability() result (first 500 chars):\n", result.content[0].text[:500])

            # # Test get_capability (specific)
            # # We need a valid title. "Embeddings" is likely to exist based on llms.txt content we saw earlier.
            # result = await session.call_tool("get_capability_page", arguments={"capability": "Embeddings"})
            # print("\nget_capability('Embeddings') result (first 500 chars):\n", result.content[0].text[:500])

            # Test search_documentation
            result = await session.call_tool("search_documentation", arguments={"queries": ["function calling"]})
            print("\nsearch_documentation('function calling') result (first 500 chars):\n", result.content[0].text[:500])

            # Test get_current_model
            # result = await session.call_tool("get_current_model", arguments={})
            # print("\nget_current_model() result (first 500 chars):\n", result.content[0].text[:500])

if __name__ == "__main__":
    asyncio.run(run())
