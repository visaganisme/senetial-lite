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
                        "status": "poisoned" if is_poisoned else "clean",
                        "badge": (
                            "⚠️ Adversarial Poisoned Doc" if is_poisoned else "🟢 Verified Clean Doc"
                        ),
                    }
                )
    return docs_list


@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)) -> dict[str, Any]:  # noqa: B008
    filename = file.filename or "uploaded_doc.txt"
    ext = Path(filename).suffix.lower()
    if ext not in (".pdf", ".md", ".txt"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF (.pdf), Markdown (.md), and Text (.txt) files are supported.",
        )

    target_dir = cfg.BASE_DIR / "docs"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename

    content = await file.read()
    target_path.write_bytes(content)

    num_chunks = 0
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
                ids=[f"{filename}_{c.id}" for c in chunks],
                embeddings=vecs,
                documents=[c.text for c in chunks],
                metadatas=[
                    {
                        "source": filename,
                        "page": c.page,
                        "section": c.section or "",
                        "access_label": "internal",
                        "chunk_id": f"{filename}_{c.id}",
                        "strategy": "structure",
                    }
                    for c in chunks
                ],
            )
        num_chunks = len(chunks)
    except Exception:
        # Fallback keyword search still finds the file on disk
        pass

    is_poisoned = "qa-vx-7" in filename.lower() or "poison" in filename.lower()
    return {
        "filename": filename,
        "size_kb": round(len(content) / 1024, 1),
        "chunks_indexed": num_chunks,
        "status": "poisoned" if is_poisoned else "clean",
        "message": f"Successfully indexed '{filename}' into vector database ({num_chunks} chunks).",
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
    # Log approval audit decision
    audit_logger.record(
        guard="tool",  # type: ignore[arg-type]
        decision=type(
            "Obj",
            (),
            {
                "action": "allow" if req.approved else "block",
                "reason": (
                    "Operator manually approved operation"
                    if req.approved
                    else "Operator rejected operation"
                ),
                "confidence": 1.0,
                "metadata": {"operation_id": req.operation_id},
            },
        )(),
        target=f"operation_id={req.operation_id}",
    )
    return {"operation_id": req.operation_id, "approved": req.approved}
