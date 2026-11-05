"""FastAPI Dashboard and Side-by-Side Comparison Demo for Sentinel."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

import sentinel.config as cfg
from sentinel.agent.graph import run_agent
from sentinel.gateway.approvals import PENDING_APPROVALS, remove_pending_approval
from sentinel.gateway.audit import AuditLogger
from sentinel.gateway.gateway import SentinelGateway
from sentinel.ingest.chunk import chunk_structure
from sentinel.ingest.embed import embed_texts
from sentinel.ingest.parse import parse_md, parse_pdf
from sentinel.ingest.store import client
from sentinel.router.router import Runtime
from sentinel.router.schema import load_models_config

app = FastAPI(title="Sentinel Lite - Security Gateway Dashboard")

DASHBOARD_DIR = Path(__file__).resolve().parent
RESULTS_DIR = DASHBOARD_DIR.parents[1] / "results"
HTML_FILE = DASHBOARD_DIR / "index.html"

audit_logger = AuditLogger()
gateway = SentinelGateway(audit_logger=audit_logger)


class QueryRequest(BaseModel):
    prompt: str = Field(..., description="Prompt or red-team payload to execute")
    mode: Literal["unprotected", "protected", "both"] = Field(
        default="both", description="Execution mode: unprotected, protected, or both"
    )
    user_access: str = Field(
        default="internal", description="User access level (internal or public)"
    )


class ApprovalRequest(BaseModel):
    operation_id: str
    approved: bool


@app.get("/", response_class=HTMLResponse)
def index_view():
    if not HTML_FILE.exists():
        raise HTTPException(status_code=404, detail="Dashboard index.html template not found")
    content = HTML_FILE.read_text(encoding="utf-8")
    return HTMLResponse(content=content, status_code=200)


@app.get("/api/stats")
def stats_view() -> dict[str, Any]:
    records = audit_logger.get_recent(500)
    blocks = sum(1 for r in records if r.action == "block")
    allows = sum(1 for r in records if r.action == "allow")
    escalates = sum(1 for r in records if r.action == "escalate")
    return {
        "total_audited": len(records),
        "blocks": blocks,
        "allows": allows,
        "escalates": escalates,
        "status": "operational",
    }


@app.get("/api/audit")
def audit_view(limit: int = 50) -> list[dict[str, Any]]:
    records = audit_logger.get_recent(limit=limit)
    return [r.model_dump() for r in records]


@app.get("/api/results")
def results_view() -> dict[str, Any]:
    baseline_file = RESULTS_DIR / "baseline_redteam.json"
    comparison_file = RESULTS_DIR / "gateway_comparison.json"
    baseline = (
        json.loads(baseline_file.read_text(encoding="utf-8")) if baseline_file.exists() else None
    )
    comparison = (
        json.loads(comparison_file.read_text(encoding="utf-8"))
        if comparison_file.exists()
        else None
    )
    return {"baseline": baseline, "comparison": comparison}


MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5 MB


@app.get("/api/documents")
def list_documents() -> list[dict[str, Any]]:
    docs_list: list[dict[str, Any]] = []
    roots = [
        (cfg.BASE_DIR / "docs_synthetic", "Synthetic & Benchmark Corpus"),
        (cfg.BASE_DIR / "docs", "User Knowledge Base"),
    ]
    for root, category in roots:
        if not root.exists():
            continue
        for path in sorted(root.glob("*")):
            if (
                path.is_file()
                and path.suffix.lower() in (".pdf", ".md", ".txt")
                and not path.name.startswith(".")
            ):
                is_poisoned = "qa-vx-7" in path.name.lower() or "poison" in path.name.lower()
                docs_list.append(
                    {
                        "name": path.name,
                        "category": category,
                        "size_kb": round(path.stat().st_size / 1024, 1),
                        "type": path.suffix.lower().replace(".", "").upper(),
                        "status": "poisoned" if is_poisoned else "active",
                        "badge": (
                            "⚠️ Adversarial Poisoned Doc" if is_poisoned else "Standard Document"
                        ),
                    }
                )
    return docs_list


@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)) -> dict[str, Any]:  # noqa: B008
    raw_filename = file.filename or ""
    clean_name = Path(raw_filename).name

    # Reject if filename contains directory traversal or differs from Path(filename).name
    has_sep = "/" in raw_filename or "\\" in raw_filename or ".." in raw_filename
    if not clean_name or raw_filename != clean_name or has_sep:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid filename '{raw_filename}': "
                "path traversal and directory separators are not allowed."
            ),
        )

    ext = Path(clean_name).suffix.lower()
    if ext not in (".pdf", ".md", ".txt"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF (.pdf), Markdown (.md), and Text (.txt) files are supported.",
        )

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File exceeds maximum allowed size of 5 MB "
                f"({len(content)} bytes > {MAX_UPLOAD_SIZE} bytes)."
            ),
        )

    target_dir = cfg.BASE_DIR / "docs"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / clean_name

    # Never overwrite existing files in docs/ or docs_synthetic/
    already_exists = target_path.exists() or (cfg.BASE_DIR / "docs_synthetic" / clean_name).exists()
    if already_exists:
        raise HTTPException(
            status_code=409,
            detail=(
                f"File '{clean_name}' already exists in knowledge base. "
                "Overwriting is not permitted."
            ),
        )

    target_path.write_bytes(content)

    try:
        if ext == ".pdf":
            doc = parse_pdf(target_path, access_label="internal")
        else:
            doc = parse_md(target_path, access_label="internal")

        chunks = chunk_structure(doc)
        cfgm = load_models_config()
        embed_entries = cfgm.roles.get("embed", [])
        if embed_entries and chunks:
            coll = client().get_collection("rag_structure_embed-v5-0-pro")
            vecs = embed_texts(embed_entries[0], [c.text for c in chunks])
            coll.add(
                ids=[f"{clean_name}_{c.id}" for c in chunks],
                embeddings=vecs,
                documents=[c.text for c in chunks],
                metadatas=[
                    {
                        "source": clean_name,
                        "page": c.page,
                        "section": c.section or "",
                        "access_label": "internal",
                        "chunk_id": f"{clean_name}_{c.id}",
                        "strategy": "structure",
                    }
                    for c in chunks
                ],
            )
        num_chunks = len(chunks)
    except Exception as e:
        if target_path.exists():
            target_path.unlink()
        raise HTTPException(
            status_code=500,
            detail=f"Document indexing failed: {e}",
        ) from e

    is_poisoned = "qa-vx-7" in clean_name.lower() or "poison" in clean_name.lower()
    return {
        "filename": clean_name,
        "size_kb": round(len(content) / 1024, 1),
        "chunks_indexed": num_chunks,
        "status": "poisoned" if is_poisoned else "active",
        "message": (
            f"Successfully indexed '{clean_name}' into vector database ({num_chunks} chunks)."
        ),
    }


@app.post("/api/query")
def query_view(req: QueryRequest) -> dict[str, Any]:
    output: dict[str, Any] = {}
    runtime = Runtime.load()

    if req.mode in ("unprotected", "both"):
        u_state = run_agent(
            prompt=req.prompt,
            gateway_mode="off",
            runtime=runtime,
            max_steps=6,
        )
        output["unprotected"] = u_state.model_dump()

    if req.mode in ("protected", "both"):
        p_state = run_agent(
            prompt=req.prompt,
            gateway_mode="on",
            runtime=runtime,
            gateway=gateway,
            max_steps=6,
        )
        output["protected"] = p_state.model_dump()

    return output


@app.post("/api/approve")
def approve_view(req: ApprovalRequest) -> dict[str, Any]:
    if not req.operation_id:
        raise HTTPException(status_code=400, detail="Missing operation_id")

    pending = PENDING_APPROVALS.get(req.operation_id)
    if not pending:
        raise HTTPException(
            status_code=404,
            detail=f"Operation '{req.operation_id}' not found or already resolved.",
        )

    tool_name = pending["tool_name"]
    args = pending["args"]

    if req.approved:
        from sentinel.mcp_servers.tools import get_victim_tools

        tools = get_victim_tools()
        tool_map = {t.name: t for t in tools}
        tool_fn = tool_map.get(tool_name)
        if not tool_fn:
            raise HTTPException(status_code=500, detail=f"Tool '{tool_name}' not available")

        try:
            result_text = tool_fn.invoke(args)
        except Exception as e:
            result_text = f"Execution error: {e}"

        audit_logger.record(
            guard="tool",  # type: ignore[arg-type]
            decision=type(
                "Obj",
                (),
                {
                    "action": "allow",
                    "reason": (
                        f"Operator approved write operation '{tool_name}' "
                        f"(ID: {req.operation_id})"
                    ),
                    "confidence": 1.0,
                    "metadata": {
                        "operation_id": req.operation_id,
                        "tool": tool_name,
                        "args": args,
                    },
                },
            )(),
            target=f"operation_id={req.operation_id} tool={tool_name}",
        )
        remove_pending_approval(req.operation_id)
        return {
            "operation_id": req.operation_id,
            "approved": True,
            "status": "executed",
            "result": str(result_text),
        }
    else:
        audit_logger.record(
            guard="tool",  # type: ignore[arg-type]
            decision=type(
                "Obj",
                (),
                {
                    "action": "block",
                    "reason": (
                        f"Operator rejected write operation '{tool_name}' "
                        f"(ID: {req.operation_id})"
                    ),
                    "confidence": 1.0,
                    "metadata": {
                        "operation_id": req.operation_id,
                        "tool": tool_name,
                        "args": args,
                    },
                },
            )(),
            target=f"operation_id={req.operation_id} tool={tool_name}",
        )
        remove_pending_approval(req.operation_id)
        return {
            "operation_id": req.operation_id,
            "approved": False,
            "status": "cancelled",
            "result": "Operation rejected by human operator.",
        }
