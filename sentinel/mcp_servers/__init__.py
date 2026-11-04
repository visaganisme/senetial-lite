"""Sentinel MCP Servers package: docs_search, eng_calc, notes_tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentinel.mcp_servers.docs_search import search_docs
    from sentinel.mcp_servers.docs_search import server as docs_search_server
    from sentinel.mcp_servers.eng_calc import calculate
    from sentinel.mcp_servers.eng_calc import server as eng_calc_server
    from sentinel.mcp_servers.notes_tasks import (
        delete_note,
        list_notes,
        read_note,
        write_note,
    )
    from sentinel.mcp_servers.notes_tasks import (
        server as notes_tasks_server,
    )

__all__ = [
    "calculate",
    "delete_note",
    "docs_search_server",
    "eng_calc_server",
    "list_notes",
    "notes_tasks_server",
    "read_note",
    "search_docs",
    "write_note",
]


def __getattr__(name: str):
    if name in ("docs_search_server", "search_docs"):
        import sentinel.mcp_servers.docs_search as ds

        return getattr(ds, "server" if name == "docs_search_server" else "search_docs")
    if name in ("eng_calc_server", "calculate"):
        import sentinel.mcp_servers.eng_calc as ec

        return getattr(ec, "server" if name == "eng_calc_server" else "calculate")
    if name in (
        "notes_tasks_server",
        "write_note",
        "read_note",
        "list_notes",
        "delete_note",
    ):
        import sentinel.mcp_servers.notes_tasks as nt

        return getattr(nt, "server" if name == "notes_tasks_server" else name)
    raise AttributeError(f"module 'sentinel.mcp_servers' has no attribute '{name}'")
