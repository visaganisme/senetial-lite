"""LangChain-compatible tool adapters for Sentinel victim agent tools.
Binds docs_search, eng_calc, and notes_tasks into standard StructuredTools.
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from sentinel.mcp_servers.docs_search import search_docs
from sentinel.mcp_servers.eng_calc import calculate
from sentinel.mcp_servers.notes_tasks import delete_note, list_notes, read_note, write_note


class DocsSearchInput(BaseModel):
    query: str = Field(description="Search query or technical question.")
    top_k: int = Field(default=5, description="Maximum number of document chunks to retrieve.")
    access_level: str = Field(
        default="internal", description="Access level: 'internal' or 'public'."
    )


class EngCalcInput(BaseModel):
    expression: str = Field(
        description="Math or engineering expression to evaluate (e.g. '25 * 1.25', 'sqrt(144)')."
    )


class WriteNoteInput(BaseModel):
    title: str = Field(description="Filename or title for the note.")
    content: str = Field(description="Text content of the note.")


class ReadNoteInput(BaseModel):
    title: str = Field(description="Filename or title of the note to retrieve.")


class DeleteNoteInput(BaseModel):
    title: str = Field(description="Filename or title of the note to delete.")


def get_victim_tools() -> list[StructuredTool]:
    """Return the list of StructuredTools available to the victim agent."""
    return [
        StructuredTool.from_function(
            func=search_docs,
            name="docs_search",
            description="Search engineering documents and guides using hybrid retrieval.",
            args_schema=DocsSearchInput,
        ),
        StructuredTool.from_function(
            func=calculate,
            name="eng_calc",
            description="Perform engineering calculations and arithmetic evaluations safely.",
            args_schema=EngCalcInput,
        ),
        StructuredTool.from_function(
            func=write_note,
            name="notes_tasks_write",
            description="Save a note or task specification to the local notes workspace.",
            args_schema=WriteNoteInput,
        ),
        StructuredTool.from_function(
            func=read_note,
            name="notes_tasks_read",
            description="Read the content of a saved note from the notes workspace.",
            args_schema=ReadNoteInput,
        ),
        StructuredTool.from_function(
            func=lambda: list_notes(),
            name="notes_tasks_list",
            description="List all available notes in the notes workspace.",
        ),
        StructuredTool.from_function(
            func=delete_note,
            name="notes_tasks_delete",
            description="Delete a note by title from the notes workspace.",
            args_schema=DeleteNoteInput,
        ),
    ]
