"""Red-team test runner for executing attack suites across target models and gateway modes."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sentinel.redteam.schema import (
    AttackCase,
    AttackExecution,
    AttackResult,
    BenignQuestion,
    GatewayAction,
    RedTeamRunSummary,
)
from sentinel.redteam.scorer import calculate_attack_metrics, evaluate_attack_result

logger = logging.getLogger(__name__)


def load_attacks(path: Path | str) -> list[AttackCase]:
    """Load attack cases from a JSONL file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Attack file not found: {p}")
    cases = []
    with p.open(encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                cases.append(AttackCase.model_validate(data))
            except Exception as e:
                logger.error(f"Failed to parse attack at line {idx} in {p}: {e}")
                raise
    return cases


def load_questions(path: Path | str) -> list[BenignQuestion]:
    """Load benign evaluation questions from JSONL."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Questions file not found: {p}")
    questions = []
    with p.open(encoding="utf-8") as f:
        for _idx, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            questions.append(BenignQuestion.model_validate(data))
    return questions


def run_attack_suite(
    attacks: list[AttackCase],
    model_id: str,
    mode: str,
    invoker_fn: Callable[[str, str], tuple[str, list[str], GatewayAction | None, float, int]],
    repetitions: int = 3,
    split_name: str = "dev",
) -> tuple[list[AttackResult], RedTeamRunSummary]:
    """Execute attacks against an invoker function with N repetitions.

    invoker_fn takes (payload, mode) and returns:
    (agent_output, tool_calls, gateway_decision, latency_ms, tokens_used)
    """
    results: list[AttackResult] = []
    all_executions: list[AttackExecution] = []
    by_category_executions: dict[str, list[AttackExecution]] = {}

    for case in attacks:
        case_executions: list[AttackExecution] = []
        for rep in range(repetitions):
            try:
                agent_output, tool_calls, decision, lat_ms, tokens = invoker_fn(case.payload, mode)
            except Exception as e:
                logger.warning(f"Error invoking attack {case.id} (rep {rep}): {e}")
                agent_output = f"Execution error: {e}"
                tool_calls = []
                decision = GatewayAction.block
                lat_ms = 0.0
                tokens = 0

            execution = evaluate_attack_result(
                case=case,
                agent_output=agent_output,
                gateway_decision=decision,
                tool_calls=tool_calls,
                latency_ms=lat_ms,
                tokens_used=tokens,
                run_index=rep,
            )
            case_executions.append(execution)
            all_executions.append(execution)

            cat_key = case.category.value
            if cat_key not in by_category_executions:
                by_category_executions[cat_key] = []
            by_category_executions[cat_key].append(execution)

        breach_rate, block_rate, avg_lat = calculate_attack_metrics(case_executions)
        results.append(
            AttackResult(
                attack_id=case.id,
                category=case.category,
                split=case.split,
                model_id=model_id,
                mode=mode,  # type: ignore[arg-type]
                executions=case_executions,
                breach_rate=breach_rate,
                block_rate=block_rate,
                avg_latency_ms=avg_lat,
            )
        )

    overall_breach, overall_block, overall_lat = calculate_attack_metrics(all_executions)

    by_category_metrics = {}
    for cat, execs in by_category_executions.items():
        c_breach, c_block, c_lat = calculate_attack_metrics(execs)
        by_category_metrics[cat] = {
            "breach_rate": round(c_breach, 4),
            "block_rate": round(c_block, 4),
            "avg_latency_ms": round(c_lat, 2),
            "count": len(execs) // repetitions,
        }

    summary = RedTeamRunSummary(
        run_id=f"run-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}",
        timestamp=datetime.now(UTC).isoformat(),
        model_id=model_id,
        mode=mode,  # type: ignore[arg-type]
        split=split_name,
        total_attacks=len(attacks),
        overall_breach_rate=round(overall_breach, 4),
        overall_block_rate=round(overall_block, 4),
        avg_latency_ms=round(overall_lat, 2),
        by_category=by_category_metrics,
    )

    return results, summary
