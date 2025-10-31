import asyncio
import json
import os
import subprocess
import sys
import shutil
from google import genai
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from typing import Dict, Any, List

# Configuration
MODEL_NAME = "gemini-flash-latest"
PROMPTS_FILE = "tests/test_prompts.json"
GENERATED_DIR = "tests/generated"

server_params = StdioServerParameters(
    command="python3",  # Executable
    args=["-m", "gemini_docs_mcp.server"],  # MCP Server
    env=None,  # Optional environment variables
)


def setup_directories():
    if os.path.exists(GENERATED_DIR):
        shutil.rmtree(GENERATED_DIR)
    os.makedirs(GENERATED_DIR)

def load_prompts() -> List[Dict[str, Any]]:
    with open(PROMPTS_FILE, 'r') as f:
        return json.load(f)

async def generate_code(prompt:str, client:genai.Client, mcp_session:ClientSession) -> str:
    print(f"Generating code for: {prompt[:100]}...")


    response = await client.aio.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
          tools=[mcp_session]
        )
    )
    
    # Extract code from markdown code blocks if present
    text = response.text
    if "```python" in text:
        code = text.split("```python")[1].split("```")[0].strip()
    elif "```" in text:
        code = text.split("```")[1].split("```")[0].strip()
    else:
        code = text.strip()
        
    return code

def save_code(code: str, test_id: str) -> str:
    file_path = os.path.join(GENERATED_DIR, f"{test_id}.py")
    with open(file_path, 'w') as f:
        f.write(code)
    return file_path

def execute_code(file_path: str) -> tuple[str, str, int]:
    print(f"Executing: {file_path}...")
    # Crucial: Add current directory to PYTHONPATH so 'python3 -m gemini_docs_mcp.server' works
    env = os.environ.copy()
    env['PYTHONPATH'] = os.getcwd() + os.pathsep + env.get('PYTHONPATH', '')
    
    try:
        # 30 second timeout to prevent hangs
        result = subprocess.run(
            [sys.executable, file_path],
            capture_output=True,
            text=True,
            env=env,
            timeout=60
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", "Execution timed out (60s)", -1
    except Exception as e:
        return "", str(e), -1

def validate_result(stdout: str, stderr: str, returncode: int) -> bool:
    if returncode != 0:
        print(f"  FAILED: Non-zero return code {returncode}")
        print(f"  STDERR: {stderr.strip()}")
        return False

    return True

async def main():
    setup_directories()
    prompts = load_prompts()
    client = genai.Client()
    
    results = {}
    
    async with stdio_client(server_params) as (read, write):
      async with ClientSession(read, write) as session:
        await session.initialize()
        for test_case in prompts:
            test_id = test_case['id']
            try:
                code = await generate_code(test_case['prompt'], client, session)
                script_path = save_code(code, test_id)
                stdout, stderr, returncode = execute_code(script_path)
                passed = validate_result(stdout, stderr, returncode)
                
                results[test_id] = {
                    "passed": passed,
                    "script": script_path
                }
                
                if passed:
                    print(f"  PASSED")
                else:
                    print(f"  FAILED")
                    
            except Exception as e:
                print(f"  ERROR during test execution: {e}")
                results[test_id] = {"passed": False, "error": str(e)}

    print("\n=== Evaluation Summary ===")
    passed_count = sum(1 for r in results.values() if r['passed'])
    total_count = len(results)
    print(f"Total Tests: {total_count}")
    print(f"Passed: {passed_count}")
    print(f"Failed: {total_count - passed_count}")
    
    if passed_count != total_count:
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
