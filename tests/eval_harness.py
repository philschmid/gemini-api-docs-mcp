import asyncio
import json
import os
import subprocess
import sys
import shutil
import argparse
import re
import datetime
from google import genai
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from typing import Dict, Any, List, Optional

# Configuration
MODEL_NAME = "gemini-flash-latest"
PROMPTS_FILE = "tests/test_prompts.json"
GENERATED_DIR = "tests/generated"
RESULT_FILE = "tests/result.json"

server_params = StdioServerParameters(
    command="python3",  # Executable
    args=["-m", "gemini_docs_mcp.server"],  # MCP Server
    env=None,  # Optional environment variables
)

# --- Code Extraction & Analysis Utils ---

def extract_code_py(response_str: str) -> str:
    """Extracts code for the given language from the response."""
    re_pattern = rf'```python\n.*?\n\s*```'
    compiled_pattern = re.compile(re_pattern, re.DOTALL)

    if found := compiled_pattern.findall(response_str):
        found = [s.strip() for s in found]
        if len(found) == 1:
            return found[0].replace("```python", "").replace("```", "").strip()

        result_str_list = []
        for i, s in enumerate(found):
            result_str_list.append(f'# chunk {i+1}')
            result_str_list.append(s.replace("```python", "").replace("```", "").strip())
        return '\n'.join(result_str_list)
    else:
        return response_str.strip()

def dedent_code_str(code_str: str) -> str:
    """Dedents the given code string."""
    code_str_lines = code_str.split('\n')
    if not code_str_lines: return code_str
    # Find first non-empty line to determine indentation
    first_line = next((line for line in code_str_lines if line.strip()), None)
    if not first_line: return code_str
    
    n_dedent = len(first_line) - len(first_line.lstrip())
    if n_dedent > 0:
        return '\n'.join([line[n_dedent:] if len(line) >= n_dedent else line for line in code_str_lines])
    return code_str

def extract_code_ts(response_str: str) -> str:
    """Extracts code for the given language from the response."""
    re_pattern = rf'```(?:typescript|javascript)\n.*?\n\s*```'
    compiled_pattern = re.compile(re_pattern, re.DOTALL)

    if found := compiled_pattern.findall(response_str):
        found = [s.strip() for s in found]

        result_str_list = []
        for i, s in enumerate(found):
            # check language
            if s.startswith('```typescript'):
                lang = 'typescript'
            elif s.startswith('```javascript'):
                lang = 'javascript'
            else:
                lang = 'unknown'
            result_str_list.append(f'//{lang} chunk {i+1}')

            # strip the quotes and dedent
            code_chunk = '\n'.join(s.split('\n')[1:-1])
            s = dedent_code_str(code_chunk)
            result_str_list.append(s)
        return '\n'.join(result_str_list)
    else:
        return '// unable to extract code\n' + response_str

def extract_code(response_str: str, lang: str) -> str:
    if lang == 'python':
        return extract_code_py(response_str)
    elif lang == 'typescript':
        return extract_code_ts(response_str)
    else:
        # Fallback for unspecified or other languages
        if "```" in response_str:
             return response_str.split("```")[1].strip()
        return response_str.strip()

OLD_PY_SDK_KEYWORDS = {
    'google.generativeai',
    'GenerativeModel',
    'GenerationConfig',
    'model.start_chat',
    'model.generate_content',
}

def check_sdk_version_py(code_str):
    if any(keyword in code_str for keyword in OLD_PY_SDK_KEYWORDS):
        return 'old_sdk'
    if 'from google import genai' in code_str or 'import google.genai' in code_str:
        return 'new_sdk'
    return 'no_sdk'

OLD_TS_SDK_KEYWORDS = {
    '@google/generative-ai',
    'GoogleGenerativeAI',
    'getGenerativeModel',
    'generationConfig',
    'model.startChat',
    'model.generateContent',
}

def check_sdk_version_ts(code_str):
    if any(keyword in code_str for keyword in OLD_TS_SDK_KEYWORDS):
        return 'old_sdk'
    if '@google/genai' in code_str:
        return 'new_sdk'
    return 'no_sdk'

def analyze_code(code: str, lang: str) -> str:
    if lang == 'python':
        return check_sdk_version_py(code)
    elif lang == 'typescript':
        return check_sdk_version_ts(code)
    else:
        return 'unknown_lang'

# --- Harness Core ---

def setup_directories():
    if os.path.exists(GENERATED_DIR):
        shutil.rmtree(GENERATED_DIR)
    os.makedirs(GENERATED_DIR)

def load_prompts() -> List[Dict[str, Any]]:
    with open(PROMPTS_FILE, 'r') as f:
        return json.load(f)

async def generate_code(prompt:str, language: str, client:genai.Client, mcp_session:ClientSession, retries=3) -> str:
    print(f"Generating code for ({language}): {prompt[:50]}...")

    for attempt in range(retries + 1):
        try:
            # Use a model that's good at coding. 
            response = await client.aio.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                  tools=[mcp_session],
                  temperature=0.1 # Lower temperature for more deterministic code
                )
            )
            return extract_code(response.text, language)
        except Exception as e:
            error_str = str(e)
            # Retry on 5XX errors or generic "Internal" errors
            is_5xx = any(code in error_str for code in ["500", "502", "503", "504", "Internal", "DeadlineExceeded"])
            if attempt < retries and is_5xx:
                wait_time = (attempt + 1) * 2 # Simple backoff: 2s, 4s, 6s
                print(f"  WARNING: API error (attempt {attempt+1}/{retries+1}): {e}. Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
            else:
                if attempt == retries and is_5xx:
                     print(f"  ERROR: Failed after {retries+1} attempts.")
                raise e
    return ""

def save_code(code: str, test_id: str, language: str) -> str:
    ext = "py" if language == "python" else "ts"
    file_path = os.path.join(GENERATED_DIR, f"{test_id}.{ext}")
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

def validate_execution_result(stdout: str, stderr: str, returncode: int) -> bool:
    if returncode != 0:
        print(f"  FAILED (Execution): Non-zero return code {returncode}")
        print(f"  STDERR: {stderr.strip()}")
        return False
    return True

async def main():
    parser = argparse.ArgumentParser(description="Gemini Docs MCP Eval Harness")
    parser.add_argument('--mode', choices=['execute', 'static'], default='static', help='Evaluation mode')
    args = parser.parse_args()

    setup_directories()
    prompts = load_prompts()
    client = genai.Client()
    
    results = {}
    
    print(f"=== Starting Evaluation (Mode: {args.mode}) ===")

    async with stdio_client(server_params) as (read, write):
      async with ClientSession(read, write) as session:
        await session.initialize()
        for test_case in prompts:
            test_id = test_case.get('id', 'unknown')
            language = test_case.get('language', 'python') # Default to python if missing
            
            print(f"\nTest: {test_id} ({language})")
            try:
                code = await generate_code(test_case['prompt'], language, client, session)
                script_path = save_code(code, test_id, language)
                
                if args.mode == 'static':
                    analysis_result = analyze_code(code, language)
                    passed = (analysis_result == 'new_sdk')
                    results[test_id] = {"passed": passed, "analysis": analysis_result, "script": script_path}
                    print(f"  Analysis: {analysis_result} -> {'PASSED' if passed else 'FAILED'}")

                elif args.mode == 'execute':
                    if language == 'python':
                        stdout, stderr, returncode = execute_code(script_path)
                        passed = validate_execution_result(stdout, stderr, returncode)
                        results[test_id] = {"passed": passed, "script": script_path}
                        print(f"  Execution -> {'PASSED' if passed else 'FAILED'}")
                    else:
                        print(f"  SKIPPED (Execution not supported for {language})")
                        results[test_id] = {"passed": None, "status": "skipped_execution"}

            except Exception as e:
                print(f"  ERROR during test execution: {e}")
                results[test_id] = {"passed": False, "error": str(e)}

    print("\n=== Evaluation Summary ===")
    passed_count = sum(1 for r in results.values() if r.get('passed') is True)
    failed_count = sum(1 for r in results.values() if r.get('passed') is False)
    skipped_count = sum(1 for r in results.values() if r.get('passed') is None)
    total_count = len(results)
    
    print(f"Total Tests: {total_count}")
    print(f"Passed: {passed_count}")
    print(f"Failed: {failed_count}")
    print(f"Skipped: {skipped_count}")

    # Generate result.json
    failures = []
    for test_id, result in results.items():
        if result.get('passed') is False:
            # Find the prompt details
            test_case = next((p for p in prompts if p.get('id') == test_id), {})
            failure_entry = {
                "id": test_id,
                "language": test_case.get('language', 'unknown'),
                "prompt": test_case.get('prompt', 'unknown'),
                "error": result.get('error'),
                "analysis": result.get('analysis'),
                "script": result.get('script')
            }
            failures.append(failure_entry)

    report = {
        "summary": {
            "total": total_count,
            "passed": passed_count,
            "failed": failed_count,
            "skipped": skipped_count
        },
        "failures": failures
    }

    with open(RESULT_FILE, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nResults saved to {RESULT_FILE}")

    # Exit with error if any failed (ignoring skipped)
    if failed_count > 0:
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
