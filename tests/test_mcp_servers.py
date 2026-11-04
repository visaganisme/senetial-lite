"""Tests for Phase-4 MCP servers (docs_search, eng_calc, notes_tasks)."""

import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from sentinel.mcp_servers.docs_search import search_docs
from sentinel.mcp_servers.eng_calc import calculate
from sentinel.mcp_servers.notes_tasks import (
    _get_target_path,
    delete_note,
    list_notes,
    read_note,
    write_note,
)
from sentinel.mcp_servers.tools import get_victim_tools


def test_eng_calc_valid_expressions():
    """Verify standard arithmetic, functions, and formatting in eng_calc."""
    assert calculate("25 * 4") == "100"
    assert calculate("100 / 4") == "25"
    assert calculate("sqrt(144) + 8") == "20"
    assert calculate("2 ** 10") == "1024"
    assert calculate("round(sin(0), 2)") == "0"


def test_eng_calc_unsafe_and_errors():
    """Verify eng_calc safely blocks code execution and invalid syntax."""
    # Code injection attempts
    assert "Calculation error" in calculate("__import__('os').system('calc.exe')")
    assert "Calculation error" in calculate("eval('open(\".env\").read()')")
    assert "Calculation error" in calculate("exec('import sys')")
    assert "Calculation error" in calculate("open('.env')")

    # Syntax and arithmetic errors
    assert "Division by zero" in calculate("10 / 0")
    assert "Exceeds numerical limits" in calculate("10 ** (10 ** 10)")
    assert "Empty expression" in calculate("")


def test_notes_tasks_crud_and_jail(tmp_path: Path, monkeypatch):
    """Verify notes write, read, list, delete, and path jail enforcement."""
    test_notes_dir = tmp_path / "test_notes"
    monkeypatch.setattr("sentinel.mcp_servers.notes_tasks.NOTES_DIR", test_notes_dir)

    # 1. Write note
    msg = write_note("spec_review", "Important pump specs verified.")
    assert "Successfully saved note" in msg
    assert (test_notes_dir / "spec_review.txt").exists()

    # 2. Read note
    content = read_note("spec_review")
    assert content == "Important pump specs verified."

    # 3. List notes
    note_list = list_notes()
    assert "spec_review.txt" in note_list

    # 4. Path jail: Path traversal must be stripped to base name inside jail
    jailed_path = _get_target_path("../../../../evil.txt")
    assert jailed_path.parent == test_notes_dir.resolve()
    assert jailed_path.name == "evil.txt"

    # 5. Delete note
    del_msg = delete_note("spec_review")
    assert "Successfully deleted note" in del_msg
    assert not (test_notes_dir / "spec_review.txt").exists()


def test_docs_search_retrieval():
    """Verify docs_search retrieves relevant chunks as valid JSON."""
    import json

    raw = search_docs("VES-9 pressure vessel working pressure", top_k=2)
    hits = json.loads(raw)
    assert isinstance(hits, list)
    assert len(hits) >= 1
    assert "source" in hits[0]
    assert "text" in hits[0]


def test_victim_tools_langchain_binding():
    """Verify that get_victim_tools returns properly configured StructuredTools."""
    tools = get_victim_tools()
    tool_names = [t.name for t in tools]
    assert "docs_search" in tool_names
    assert "eng_calc" in tool_names
    assert "notes_tasks_write" in tool_names
    assert "notes_tasks_read" in tool_names
    assert "notes_tasks_list" in tool_names

    # Test invoking via StructuredTool
    calc_tool = next(t for t in tools if t.name == "eng_calc")
    res = calc_tool.invoke({"expression": "50 + 25"})
    assert res == "75"


def test_mcp_external_client_stdio():
    """Prove external MCP client compatibility by spawning an MCP server via stdio."""
    import asyncio

    async def _run():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "sentinel.mcp_servers.eng_calc"],
        )
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tool_list = await session.list_tools()
            names = [t.name for t in tool_list.tools]
            assert "eng_calc" in names

            call_res = await session.call_tool("eng_calc", {"expression": "12 * 12"})
            assert call_res.content[0].text == "144"

    asyncio.run(_run())
