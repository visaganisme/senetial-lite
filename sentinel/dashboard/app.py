"""FastAPI Dashboard and Side-by-Side Comparison Demo for Sentinel."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from sentinel.agent.graph import run_agent
from sentinel.gateway.audit import AuditLogger
from sentinel.gateway.gateway import SentinelGateway
from sentinel.router.router import Runtime

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


@app.post("/api/query")
def query_view(req: QueryRequest) -> dict[str, Any]:
    output: dict[str, Any] = {}
    runtime = Runtime.load()

    if req.mode in ("unprotected", "both"):
        u_state = run_agent(
            prompt=req.prompt,
            gateway_mode="off",
            runtime=runtime,
            max_steps=4,
        )
        output["unprotected"] = u_state.model_dump()

    if req.mode in ("protected", "both"):
        p_state = run_agent(
            prompt=req.prompt,
            gateway_mode="on",
            runtime=runtime,
            gateway=gateway,
            max_steps=4,
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
