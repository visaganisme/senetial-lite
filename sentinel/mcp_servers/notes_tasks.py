"""MCP Server: notes_tasks
Exposes note-taking, task tracking, and persistence tools for agents.
Writes are path-jailed to REPO_ROOT / 'notes'.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.mcpserver import MCPServer

import sentinel.config as cfg

server = MCPServer("notes_tasks")

NOTES_DIR = cfg.NOTES_DIR


def _get_target_path(title: str) -> Path:
    """Resolve and path-jail the target file strictly within NOTES_DIR."""
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    # Strip directory components to enforce path jail
    safe_name = Path(title).name
    if not safe_name or safe_name in (".", ".."):
        safe_name = "untitled.txt"
    if not safe_name.endswith(".txt"):
        safe_name = f"{safe_name}.txt"

    target = (NOTES_DIR / safe_name).resolve()
    # Path jail validation
    if not str(target).startswith(str(NOTES_DIR.resolve())):
        raise PermissionError(f"Access denied: Path '{title}' escapes the sandbox directory")
    return target


def write_note(title: str, content: str) -> str:
    """Write or update a note in the local notes directory."""
    try:
        path = _get_target_path(title)
        path.write_text(content, encoding="utf-8")
        return f"Successfully saved note '{path.name}' ({len(content)} characters)"
    except Exception as e:
        return f"Error writing note: {e}"


def read_note(title: str) -> str:
    """Read a note from the local notes directory."""
    try:
        path = _get_target_path(title)
        if not path.exists():
            return f"Error: Note '{path.name}' not found"
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading note: {e}"


def list_notes() -> str:
    """List all saved notes in the notes directory."""
    try:
        NOTES_DIR.mkdir(parents=True, exist_ok=True)
        files = [p.name for p in sorted(NOTES_DIR.glob("*.txt")) if p.is_file()]
        return json.dumps(files, indent=2)
    except Exception as e:
        return f"Error listing notes: {e}"


def delete_note(title: str) -> str:
    """Delete a note from the notes directory."""
    try:
        path = _get_target_path(title)
        if not path.exists():
            return f"Note '{path.name}' does not exist"
        path.unlink()
        return f"Successfully deleted note '{path.name}'"
    except Exception as e:
        return f"Error deleting note: {e}"


@server.tool()
def save_note(title: str, content: str) -> str:
    """Save a note or task specification to the notes workspace."""
    return write_note(title, content)


@server.tool()
def get_note(title: str) -> str:
    """Retrieve the content of a saved note by title."""
    return read_note(title)


@server.tool()
def get_all_notes() -> str:
    """List all available note filenames in the notes workspace."""
    return list_notes()


@server.tool()
def remove_note(title: str) -> str:
    """Remove a note by title."""
    return delete_note(title)


if __name__ == "__main__":
    server.run(transport="stdio")
