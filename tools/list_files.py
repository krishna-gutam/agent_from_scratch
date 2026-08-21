import json
from pathlib import Path

from .decorator import tool

WORKSPACE = Path.cwd().resolve()
EXCLUDED_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
}


@tool(
    "List files and directories inside the workspace. "
    "Use directory_path to select a directory, recursive to include "
    "nested files, and pattern to filter results, such as '*.py'."
)
def list_files(
    directory_path: str = ".",
    recursive: bool = False,
    pattern: str = "*",
) -> str:
    """List files and directories without leaving the workspace."""
    requested_directory = (WORKSPACE / directory_path).resolve()

    try:
        relative_directory = requested_directory.relative_to(WORKSPACE)
    except ValueError:
        return json.dumps({"error": "Access outside the workspace is not allowed."})

    if not requested_directory.exists():
        return json.dumps({"error": f"Directory {directory_path!r} does not exist."})

    if not requested_directory.is_dir():
        return json.dumps({"error": f"Path {directory_path!r} is not a directory."})

    iterator = (
        requested_directory.rglob(pattern)
        if recursive
        else requested_directory.glob(pattern)
    )

    entries = []
    for path in sorted(iterator):
        relative_path = path.relative_to(WORKSPACE)

        if any(part in EXCLUDED_DIRECTORIES for part in relative_path.parts):
            continue

        entries.append(
            {
                "name": path.name,
                "path": relative_path.as_posix(),
                "type": "directory" if path.is_dir() else "file",
                "size_bytes": path.stat().st_size if path.is_file() else None,
            }
        )

    return json.dumps(
        {
            "directory": relative_directory.as_posix() or ".",
            "recursive": recursive,
            "pattern": pattern,
            "count": len(entries),
            "entries": entries,
        }
    )
