import os
import asyncio
from google import genai # pip install google-genai 
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


client = genai.Client()


server_params = StdioServerParameters(
    command="gemini-docs-mcp",
    env=None,
)

async def run():
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            prompt = "Create an example on how to funciton calling with gemini 2.5 flash"

            await session.initialize()
            response = await client.aio.models.generate_content(
                model="gemini-flash-latest",
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    tools=[session], 
                ),
            )
            print(response.text)
            print(response.automatic_function_calling_history)

if __name__ == "__main__":
    asyncio.run(run())