# Local Python MCP Server - replaces E2B cloud sandbox with local execution
# Copyright (c) 2025 MiroMind (modified for local use)

import asyncio
import os
import shlex
import subprocess
import tempfile
import uuid
from urllib.parse import urlparse

from fastmcp import FastMCP

mcp = FastMCP("local-python-interpreter")

LOGS_DIR = os.environ.get("LOGS_DIR", "../../logs")
DEFAULT_TIMEOUT = 120  # seconds
MAX_RESULT_LEN = 20_000
MAX_ERROR_LEN = 4_000

# Store sandbox working directories
_sandboxes = {}


def truncate_result(result: str) -> str:
    if len(result) > MAX_RESULT_LEN:
        result = result[:MAX_RESULT_LEN] + " [Result truncated due to length limit]"
    return result


@mcp.tool()
async def create_sandbox(timeout: int = DEFAULT_TIMEOUT) -> str:
    """Create a local sandbox (working directory).

    Args:
        timeout: Time in seconds (unused in local mode, kept for compatibility).

    Returns:
        The sandbox_id of the newly created sandbox.
    """
    sandbox_id = f"local-{uuid.uuid4().hex[:8]}"
    work_dir = tempfile.mkdtemp(prefix=f"miro_sandbox_{sandbox_id}_")
    _sandboxes[sandbox_id] = work_dir
    
    tmpfiles_dir = os.path.join(LOGS_DIR, "tmpfiles")
    os.makedirs(tmpfiles_dir, exist_ok=True)
    
    return f"Sandbox created with sandbox_id: {sandbox_id}"


def _get_sandbox_dir(sandbox_id: str) -> str:
    if sandbox_id not in _sandboxes:
        # Auto-create if not exists
        work_dir = tempfile.mkdtemp(prefix=f"miro_sandbox_{sandbox_id}_")
        _sandboxes[sandbox_id] = work_dir
    return _sandboxes[sandbox_id]


@mcp.tool()
async def run_command(command: str, sandbox_id: str) -> str:
    """Execute a shell command locally.

    Args:
        command: The command to execute.
        sandbox_id: The id of the sandbox.

    Returns:
        Command result with stdout, stderr, and exit_code.
    """
    work_dir = _get_sandbox_dir(sandbox_id)
    
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
            env={**os.environ, "HOME": work_dir},
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=DEFAULT_TIMEOUT)
        
        result = f"CommandResult(stdout='{stdout.decode('utf-8', errors='replace')}', stderr='{stderr.decode('utf-8', errors='replace')}', exit_code={proc.returncode})"
        return truncate_result(result)
    except asyncio.TimeoutError:
        return f"[ERROR]: Command timed out after {DEFAULT_TIMEOUT}s"
    except Exception as e:
        return f"[ERROR]: {type(e).__name__}: {str(e)[:MAX_ERROR_LEN]}"


@mcp.tool()
async def run_python_code(code_block: str, sandbox_id: str) -> str:
    """Run Python code locally and return the result.

    Args:
        code_block: The python code to run.
        sandbox_id: The id of the sandbox.

    Returns:
        Execution result with stdout, stderr, and exit_code.
    """
    work_dir = _get_sandbox_dir(sandbox_id)
    
    # Write code to temp file
    code_file = os.path.join(work_dir, f"_run_{uuid.uuid4().hex[:6]}.py")
    with open(code_file, "w") as f:
        f.write(code_block)
    
    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", code_file,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
            env={**os.environ, "HOME": work_dir},
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=DEFAULT_TIMEOUT)
        
        result = f"Execution(stdout='{stdout.decode('utf-8', errors='replace')}', stderr='{stderr.decode('utf-8', errors='replace')}', exit_code={proc.returncode})"
        return truncate_result(result)
    except asyncio.TimeoutError:
        return f"[ERROR]: Code execution timed out after {DEFAULT_TIMEOUT}s"
    except Exception as e:
        return f"[ERROR]: {type(e).__name__}: {str(e)[:MAX_ERROR_LEN]}"
    finally:
        try:
            os.unlink(code_file)
        except:
            pass


@mcp.tool()
async def upload_file_from_local_to_sandbox(
    sandbox_id: str, local_file_path: str, sandbox_file_path: str = "/home/user"
) -> str:
    """Copy a local file into the sandbox working directory.

    Args:
        sandbox_id: The sandbox id.
        local_file_path: Path of the source file.
        sandbox_file_path: Destination path in sandbox.

    Returns:
        The path of the uploaded file.
    """
    work_dir = _get_sandbox_dir(sandbox_id)
    
    if not os.path.exists(local_file_path):
        return f"[ERROR]: Local file does not exist: {local_file_path}"
    
    dest = os.path.join(work_dir, os.path.basename(local_file_path))
    try:
        import shutil
        shutil.copy2(local_file_path, dest)
        return f"File uploaded to {dest}"
    except Exception as e:
        return f"[ERROR]: {str(e)[:MAX_ERROR_LEN]}"


@mcp.tool()
async def download_file_from_internet_to_sandbox(
    sandbox_id: str, url: str, sandbox_file_path: str = "/home/user"
) -> str:
    """Download a file from the internet to the sandbox.

    Args:
        sandbox_id: The sandbox id.
        url: URL to download.
        sandbox_file_path: Destination directory.

    Returns:
        The path of the downloaded file.
    """
    work_dir = _get_sandbox_dir(sandbox_id)
    
    parsed = urlparse(url)
    basename = os.path.basename(parsed.path) or "downloaded_file"
    dest = os.path.join(work_dir, basename)
    
    try:
        proc = await asyncio.create_subprocess_exec(
            "wget", "-q", url, "-O", dest,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
        )
        await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode == 0:
            return f"File downloaded to {dest}"
        else:
            return f"[ERROR]: wget failed with exit code {proc.returncode}"
    except Exception as e:
        return f"[ERROR]: {str(e)[:MAX_ERROR_LEN]}"


@mcp.tool()
async def download_file_from_sandbox_to_local(
    sandbox_id: str, sandbox_file_path: str, local_filename: str = None
) -> str:
    """Copy a file from sandbox to local logs directory.

    Args:
        sandbox_id: The sandbox id.
        sandbox_file_path: Path in sandbox.
        local_filename: Optional filename.

    Returns:
        The local path of the file.
    """
    work_dir = _get_sandbox_dir(sandbox_id)
    
    src = os.path.join(work_dir, os.path.basename(sandbox_file_path))
    if not os.path.exists(src):
        src = sandbox_file_path  # Try absolute path
    
    if not os.path.exists(src):
        return f"[ERROR]: File not found: {sandbox_file_path}"
    
    tmpfiles_dir = os.path.join(LOGS_DIR, "tmpfiles")
    os.makedirs(tmpfiles_dir, exist_ok=True)
    
    if not local_filename:
        local_filename = os.path.basename(sandbox_file_path)
    
    dest = os.path.join(tmpfiles_dir, f"sandbox_{sandbox_id}_{local_filename}")
    
    try:
        import shutil
        shutil.copy2(src, dest)
        return f"File downloaded successfully to: {dest}"
    except Exception as e:
        return f"[ERROR]: {str(e)[:MAX_ERROR_LEN]}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
