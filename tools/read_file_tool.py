import json
from pathlib import Path

from .decorator import tool

WORKSPACE = Path.cwd().resolve()


@tool("Read a local UTF-8 text file in the workspace.")
def read_file_tool(file_path: str) -> str:
    requested_path = (WORKSPACE / file_path).resolve()

    try:
        requested_path.relative_to(WORKSPACE)
    except ValueError:
        return json.dumps({"error": "Access outside the workspace is not allowed."})

    if not requested_path.is_file():
        return json.dumps({"error": f"File {file_path!r} not found."})

    try:
        content = requested_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return json.dumps({"error": "The requested file is not UTF-8 text."})

    return json.dumps({"content": content})
