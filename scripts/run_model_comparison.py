"""Phase 8: Comprehensive Protected vs Unprotected Model Benchmark Runner.
Evaluates block rate, breach rate, inconclusive rate, errors, false-positive rate,
and latency overhead across models on the full dev set (3 runs per attack)
and benign questions.

Features:
- Immediately streams every result row to results/raw/benchmark_runs.jsonl
- Skips rows already done when restarted
- CLI flags: --model and --limit
- Scores with Sentinel Scorer (breach, block, inconclusive)
- Classifier ON
- Generates reports entirely from computed data
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sentinel.agent.graph import run_agent
from sentinel.gateway.gateway import SentinelGateway
from sentinel.redteam.runner import load_attacks, load_questions
from sentinel.redteam.schema import AttackCase, BenignQuestion, GatewayAction
from sentinel.redteam.scorer import evaluate_attack_result
from sentinel.router.schema import ChainEntry, ModelsConfig, load_models_config

logger = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"
RAW_RESULTS_DIR = RESULTS_DIR / "raw"
RAW_RESULTS_FILE = RAW_RESULTS_DIR / "benchmark_runs.jsonl"
EVALS_DIR = Path(__file__).resolve().parents[1] / "evals"

MODELS_TO_EVALUATE = [
    ChainEntry(
        provider="groq",
        model="openai/gpt-oss-120b",
        capabilities=["chat", "structured", "tools"],
    ),
    ChainEntry(
        provider="cohere",
        model="command-a-plus-05-2026",
        capabilities=["chat", "structured", "tools"],
    ),
    ChainEntry(
        provider="cohere",
        model="command-r7b-12-2024",
        capabilities=["chat", "structured"],
    ),
    ChainEntry(
        provider="groq",
        model="qwen/qwen3.8-27b",
        capabilities=["chat", "structured", "tools"],
    ),
    ChainEntry(
        provider="openrouter",
        model="nvidia/nemotron-3-ultra-550b-a55b:free",
        capabilities=["chat", "structured"],
    ),
]


def load_completed_runs() -> dict[tuple[str, str, str, int], dict]:
    """Load previously completed runs from JSONL file for resumption."""
    completed: dict[tuple[str, str, str, int], dict] = {}
    if not RAW_RESULTS_FILE.exists():
        return completed
    with RAW_RESULTS_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                key = (
                    row["model"],
                    row["mode"],
                    str(row.get("item_id", "")),
                    int(row.get("run_index", 0)),
                )
                completed[key] = row
            except Exception:
                continue
    return completed


def append_raw_result(row: dict) -> None:
    """Immediately write a result row to JSONL file."""
    RAW_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with RAW_RESULTS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
        f.flush()


def evaluate_model_on_suite(
    entry: ChainEntry,
    attacks: list[AttackCase],
    questions: list[BenignQuestion],
    gateway: SentinelGateway,
    repetitions: int = 3,
    completed_runs: dict[tuple[str, str, str, int], dict] | None = None,
) -> dict:
    from sentinel.router.router import Runtime

    completed = completed_runs or {}
    base_config = load_models_config()
    config = ModelsConfig(
        roles={"answer": [entry]},
        limits=base_config.limits,
    )
    runtime = Runtime(config, use_cache=True)

    model_label = f"{entry.provider}/{entry.model}"
    print("\n========================================================")
    print(f"Evaluating: {model_label} (Repetitions: {repetitions})")
    print("========================================================")

    # 1. Unprotected run on attacks
    unprot_breaches = 0
    unprot_blocks = 0
    unprot_gw_blocks = 0
    unprot_model_refusals = 0
    unprot_inconclusive = 0
    unprot_errors = 0
    unprot_latencies: list[float] = []

    print(f"[1/3] Running UNPROTECTED attacks ({len(attacks)} attacks x {repetitions} reps)...")
    for atk in attacks:
        for rep in range(repetitions):
            key = (model_label, "unprotected", str(atk.id), rep)
            if key in completed:
                cached = completed[key]
                if cached.get("error"):
                    unprot_errors += 1
                else:
                    unprot_latencies.append(cached.get("latency_ms", 0.0))
                    if cached.get("compromised"):
                        unprot_breaches += 1
                    elif cached.get("blocked"):
                        unprot_blocks += 1
                        if cached.get("blocked_by_gateway"):
                            unprot_gw_blocks += 1
                        else:
                            unprot_model_refusals += 1
                    elif cached.get("inconclusive"):
                        unprot_inconclusive += 1
                continue

            start = time.perf_counter()
            try:
                state = run_agent(atk.payload, gateway_mode="off", runtime=runtime, max_steps=4)
                lat = (time.perf_counter() - start) * 1000
                unprot_latencies.append(lat)

                if state.status == "error":
                    unprot_errors += 1
                    append_raw_result(
                        {
                            "model": model_label,
                            "mode": "unprotected",
                            "item_id": atk.id,
                            "run_index": rep,
                            "status": "error",
                            "error": state.status_reason or "Agent returned error status",
                            "latency_ms": lat,
                            "guard_latency_ms": 0.0,
                            "tokens_used": state.tokens_used,
                        }
                    )
                    continue

                tool_names = [f"call:{t.get('tool')}" for t in state.tool_trace]
                exec_res = evaluate_attack_result(
                    case=atk,
                    agent_output=state.final_answer,
                    gateway_decision=None,
                    tool_calls=tool_names,
                    latency_ms=lat,
                    tokens_used=state.tokens_used,
                    run_index=rep,
                )

                if exec_res.compromised:
                    unprot_breaches += 1
                elif exec_res.blocked:
                    unprot_blocks += 1
                    if exec_res.blocked_by_gateway:
                        unprot_gw_blocks += 1
                    elif exec_res.refused_by_model:
                        unprot_model_refusals += 1
                elif exec_res.inconclusive:
                    unprot_inconclusive += 1

                append_raw_result(
                    {
                        "model": model_label,
                        "mode": "unprotected",
                        "item_id": atk.id,
                        "run_index": rep,
                        "status": state.status,
                        "compromised": exec_res.compromised,
                        "blocked": exec_res.blocked,
                        "blocked_by_gateway": exec_res.blocked_by_gateway,
                        "refused_by_model": exec_res.refused_by_model,
                        "inconclusive": exec_res.inconclusive,
                        "reason": exec_res.reason,
                        "latency_ms": lat,
                        "guard_latency_ms": 0.0,
                        "tokens_used": state.tokens_used,
                        "tool_calls": tool_names,
                    }
                )
            except Exception as e:
                lat = (time.perf_counter() - start) * 1000
                unprot_latencies.append(lat)
                unprot_errors += 1
                logger.warning(f"Unprotected attack error on {atk.id} rep {rep}: {e}")
                append_raw_result(
                    {
                        "model": model_label,
                        "mode": "unprotected",
                        "item_id": atk.id,
                        "run_index": rep,
                        "status": "exception",
                        "error": str(e),
                        "latency_ms": lat,
                        "guard_latency_ms": 0.0,
                    }
                )

    # 2. Protected run on attacks (Sentinel Gateway ON, Classifier ON)
    prot_breaches = 0
    prot_blocks = 0
    prot_gw_blocks = 0
    prot_model_refusals = 0
    prot_inconclusive = 0
    prot_errors = 0
    prot_latencies: list[float] = []
    prot_guard_latencies: list[float] = []

    print(f"[2/3] Running PROTECTED attacks ({len(attacks)} attacks x {repetitions} reps)...")
    for atk in attacks:
        for rep in range(repetitions):
            key = (model_label, "protected", str(atk.id), rep)
            if key in completed:
                cached = completed[key]
                if cached.get("error"):
                    prot_errors += 1
                else:
                    prot_latencies.append(cached.get("latency_ms", 0.0))
                    prot_guard_latencies.append(cached.get("guard_latency_ms", 0.0))
                    if cached.get("compromised"):
                        prot_breaches += 1
                    elif cached.get("blocked"):
                        prot_blocks += 1
                        if cached.get("blocked_by_gateway"):
                            prot_gw_blocks += 1
                        else:
                            prot_model_refusals += 1
                    elif cached.get("inconclusive"):
                        prot_inconclusive += 1
                continue

            start = time.perf_counter()
            try:
                state = run_agent(
                    atk.payload,
                    gateway_mode="on",
                    runtime=runtime,
                    gateway=gateway,
                    max_steps=4,
                )
                lat = (time.perf_counter() - start) * 1000
                prot_latencies.append(lat)
                prot_guard_latencies.append(state.guard_latency_ms)

                if state.status == "error":
                    prot_errors += 1
                    append_raw_result(
                        {
                            "model": model_label,
                            "mode": "protected",
                            "item_id": atk.id,
                            "run_index": rep,
                            "status": "error",
                            "error": state.status_reason or "Agent returned error status",
                            "latency_ms": lat,
                            "guard_latency_ms": state.guard_latency_ms,
                            "tokens_used": state.tokens_used,
                        }
                    )
                    continue

                is_gw_blocked = state.status == "blocked" or any(
                    d.get("action") in ("block", "escalate") for d in state.gateway_decisions
                )
                gw_decision: GatewayAction | None = GatewayAction.block if is_gw_blocked else None

                tool_names = [f"call:{t.get('tool')}" for t in state.tool_trace]
                exec_res = evaluate_attack_result(
                    case=atk,
                    agent_output=state.final_answer,
                    gateway_decision=gw_decision,
                    tool_calls=tool_names,
                    latency_ms=lat,
                    tokens_used=state.tokens_used,
                    run_index=rep,
                )

                if exec_res.compromised:
                    prot_breaches += 1
                elif exec_res.blocked:
                    prot_blocks += 1
                    if exec_res.blocked_by_gateway:
                        prot_gw_blocks += 1
                    elif exec_res.refused_by_model:
                        prot_model_refusals += 1
                elif exec_res.inconclusive:
                    prot_inconclusive += 1

                append_raw_result(
                    {
                        "model": model_label,
                        "mode": "protected",
                        "item_id": atk.id,
                        "run_index": rep,
                        "status": state.status,
                        "compromised": exec_res.compromised,
                        "blocked": exec_res.blocked,
                        "blocked_by_gateway": exec_res.blocked_by_gateway,
                        "refused_by_model": exec_res.refused_by_model,
                        "inconclusive": exec_res.inconclusive,
                        "reason": exec_res.reason,
                        "latency_ms": lat,
                        "guard_latency_ms": state.guard_latency_ms,
                        "tokens_used": state.tokens_used,
                        "tool_calls": tool_names,
                        "gateway_decisions": state.gateway_decisions,
                    }
                )
            except Exception as e:
                lat = (time.perf_counter() - start) * 1000
                prot_latencies.append(lat)
                prot_guard_latencies.append(0.0)
                prot_errors += 1
                logger.warning(f"Protected attack error on {atk.id} rep {rep}: {e}")
                append_raw_result(
                    {
                        "model": model_label,
                        "mode": "protected",
                        "item_id": atk.id,
                        "run_index": rep,
                        "status": "exception",
                        "error": str(e),
                        "latency_ms": lat,
                        "guard_latency_ms": 0.0,
                    }
                )

    # 3. False Positive Rate on Benign Questions (Gateway ON)
    benign_blocks = 0
    benign_errors = 0
    print(f"[3/3] Evaluating FPR on {len(questions)} benign questions...")
    for q in questions:
        key = (model_label, "benign", str(q.id), 0)
        if key in completed:
            cached = completed[key]
            if cached.get("error"):
                benign_errors += 1
            elif cached.get("blocked"):
                benign_blocks += 1
            continue

        try:
            state = run_agent(
                q.question,
                gateway_mode="on",
                runtime=runtime,
                gateway=gateway,
                max_steps=4,
            )
            is_blocked = state.status == "blocked" or any(
                d.get("action") == "block" for d in state.gateway_decisions
            )
            if is_blocked:
                benign_blocks += 1
            elif state.status == "error":
                benign_errors += 1

            append_raw_result(
                {
                    "model": model_label,
                    "mode": "benign",
                    "item_id": q.id,
                    "run_index": 0,
                    "status": state.status,
                    "blocked": is_blocked,
                    "error": state.status_reason if state.status == "error" else None,
                    "tokens_used": state.tokens_used,
                    "guard_latency_ms": state.guard_latency_ms,
                }
            )
        except Exception as e:
            benign_errors += 1
            logger.warning(f"Benign question error on {q.id}: {e}")
            append_raw_result(
                {
                    "model": model_label,
                    "mode": "benign",
                    "item_id": q.id,
                    "run_index": 0,
                    "status": "exception",
                    "error": str(e),
                }
            )

    total_attack_runs = len(attacks) * repetitions
    valid_u_runs = max(0, total_attack_runs - unprot_errors)
    valid_p_runs = max(0, total_attack_runs - prot_errors)
    valid_q_runs = max(0, len(questions) - benign_errors)

    u_breach_rate = round(unprot_breaches / valid_u_runs, 4) if valid_u_runs else 0.0
    u_block_rate = round(unprot_blocks / valid_u_runs, 4) if valid_u_runs else 0.0
    u_gw_block_rate = round(unprot_gw_blocks / valid_u_runs, 4) if valid_u_runs else 0.0
    u_model_refusal_rate = round(unprot_model_refusals / valid_u_runs, 4) if valid_u_runs else 0.0
    u_inconc_rate = round(unprot_inconclusive / valid_u_runs, 4) if valid_u_runs else 0.0
    u_err_rate = round(unprot_errors / total_attack_runs, 4) if total_attack_runs else 0.0

    p_breach_rate = round(prot_breaches / valid_p_runs, 4) if valid_p_runs else 0.0
    p_block_rate = round(prot_blocks / valid_p_runs, 4) if valid_p_runs else 0.0
    p_gw_block_rate = round(prot_gw_blocks / valid_p_runs, 4) if valid_p_runs else 0.0
    p_model_refusal_rate = round(prot_model_refusals / valid_p_runs, 4) if valid_p_runs else 0.0
    p_inconc_rate = round(prot_inconclusive / valid_p_runs, 4) if valid_p_runs else 0.0
    p_err_rate = round(prot_errors / total_attack_runs, 4) if total_attack_runs else 0.0

    fpr = round(benign_blocks / valid_q_runs, 4) if valid_q_runs else 0.0

    avg_u_lat = round(sum(unprot_latencies) / len(unprot_latencies), 2) if unprot_latencies else 0.0
    avg_p_lat = round(sum(prot_latencies) / len(prot_latencies), 2) if prot_latencies else 0.0
    avg_p_guard_lat = (
        round(sum(prot_guard_latencies) / len(prot_guard_latencies), 2)
        if prot_guard_latencies
        else 0.0
    )
    # Overhead as measured, including negative values (no clamping)
    overhead_ms = round(avg_p_lat - avg_u_lat, 2)

    return {
        "model": model_label,
        "provider": entry.provider,
        "total_attack_runs": total_attack_runs,
        "unprotected": {
            "breach_rate": u_breach_rate,
            "block_rate": u_block_rate,
            "blocked_by_gateway_rate": u_gw_block_rate,
            "refused_by_model_rate": u_model_refusal_rate,
            "inconclusive_rate": u_inconc_rate,
            "errors": unprot_errors,
            "error_rate": u_err_rate,
            "latency_ms": avg_u_lat,
            "guard_latency_ms": 0.0,
        },
        "protected": {
            "breach_rate": p_breach_rate,
            "block_rate": p_block_rate,
            "blocked_by_gateway_rate": p_gw_block_rate,
            "refused_by_model_rate": p_model_refusal_rate,
            "inconclusive_rate": p_inconc_rate,
            "errors": prot_errors,
            "error_rate": p_err_rate,
            "latency_ms": avg_p_lat,
            "guard_latency_ms": avg_p_guard_lat,
        },
        "benign": {
            "total_questions": len(questions),
            "blocks": benign_blocks,
            "errors": benign_errors,
            "false_positive_rate": fpr,
        },
        "overhead_ms": overhead_ms,
    }


def write_reports(metrics_list: list[dict]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Generate results/gateway_comparison.md from computed data only
    gw_lines = [
        "# Sentinel Gateway — Protected vs Unprotected Model Benchmark Report",
        "",
        "Evaluation of Sentinel Gateway across LLM backends on the red-team attack suite",
        "and benign evaluation queries. All metrics are computed directly from benchmark execution.",
        "",
        "## Comparative Metrics Table",
        "",
        "| Model | Provider | Unprot Breach % | Unprot Refusal % | Prot Blocked by Gateway % | Prot Refused by Model % | Prot Breach % | Prot Inconc % | Prot Errors | FPR % | Unprot Lat (ms) | Prot Lat (ms) | Guard Time (ms) | Overhead (ms) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    for m in metrics_list:
        u = m["unprotected"]
        p = m["protected"]
        b = m["benign"]
        ov = f"+{m['overhead_ms']}" if m["overhead_ms"] > 0 else f"{m['overhead_ms']}"
        gw_lines.append(
            f"| `{m['model']}` | {m['provider']} | "
            f"{u['breach_rate'] * 100:.1f}% | {u['refused_by_model_rate'] * 100:.1f}% | "
            f"{p['blocked_by_gateway_rate'] * 100:.1f}% | {p['refused_by_model_rate'] * 100:.1f}% | "
            f"{p['breach_rate'] * 100:.1f}% | {p['inconclusive_rate'] * 100:.1f}% | {p['errors']} | "
            f"{b['false_positive_rate'] * 100:.1f}% | {u['latency_ms']:.1f} | {p['latency_ms']:.1f} | "
            f"{p['guard_latency_ms']:.1f} | {ov} |"
        )

    # Summary statistics computed from data
    n_models = len(metrics_list)
    if n_models > 0:
        avg_u_breach = sum(m["unprotected"]["breach_rate"] for m in metrics_list) / n_models
        avg_p_gw_block = (
            sum(m["protected"]["blocked_by_gateway_rate"] for m in metrics_list) / n_models
        )
        avg_p_model_refusal = (
            sum(m["protected"]["refused_by_model_rate"] for m in metrics_list) / n_models
        )
        avg_p_breach = sum(m["protected"]["breach_rate"] for m in metrics_list) / n_models
        avg_fpr = sum(m["benign"]["false_positive_rate"] for m in metrics_list) / n_models
        avg_guard_lat = sum(m["protected"]["guard_latency_ms"] for m in metrics_list) / n_models
        avg_ov = sum(m["overhead_ms"] for m in metrics_list) / n_models
        total_u_err = sum(m["unprotected"]["errors"] for m in metrics_list)
        total_p_err = sum(m["protected"]["errors"] for m in metrics_list)

        gw_lines.extend(
            [
                "",
                "## Summary Statistics (Computed from Data)",
                "",
                f"- **Models Evaluated**: {n_models}",
                f"- **Average Unprotected Breach Rate**: {avg_u_breach * 100:.1f}%",
                f"- **Average Protected Blocked by Gateway Rate**: {avg_p_gw_block * 100:.1f}%",
                f"- **Average Protected Refused by Model Rate**: {avg_p_model_refusal * 100:.1f}%",
                f"- **Average Protected Breach Rate**: {avg_p_breach * 100:.1f}%",
                f"- **Average False Positive Rate (FPR)**: {avg_fpr * 100:.1f}%",
                f"- **Average Guard Latency (Time in Guards)**: {avg_guard_lat:.2f} ms",
                f"- **Average Gateway Latency Overhead**: {avg_ov:+.2f} ms",
                f"- **Total Execution Errors**: Unprotected = {total_u_err}, Protected = {total_p_err}",
            ]
        )

    (RESULTS_DIR / "gateway_comparison.md").write_text("\n".join(gw_lines), encoding="utf-8")

    # 2. Generate results/model_comparison.md from computed data only
    mc_lines = [
        "# Sentinel Gateway — Model Usability & Routing Benchmark",
        "",
        "Empirical measurement of model suitability under the Sentinel Security Gateway.",
        "Generated from computed benchmark data without hardcoded assertions.",
        "",
        "## Model Usability Breakdown",
        "",
        "| Model | Provider | Blocked by Gateway % | Refused by Model % | Breach Rate | Inconclusive Rate | Attack Errors | Benign FPR | Protected Latency (ms) | Guard Time (ms) | Latency Overhead (ms) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    for m in metrics_list:
        p = m["protected"]
        b = m["benign"]
        ov = f"+{m['overhead_ms']}" if m["overhead_ms"] > 0 else f"{m['overhead_ms']}"
        mc_lines.append(
            f"| `{m['model']}` | {m['provider']} | "
            f"{p['blocked_by_gateway_rate'] * 100:.1f}% | {p['refused_by_model_rate'] * 100:.1f}% | "
            f"{p['breach_rate'] * 100:.1f}% | {p['inconclusive_rate'] * 100:.1f}% | {p['errors']} | "
            f"{b['false_positive_rate'] * 100:.1f}% | {p['latency_ms']:.1f} | {p['guard_latency_ms']:.1f} | {ov} |"
        )

    (RESULTS_DIR / "model_comparison.md").write_text("\n".join(mc_lines), encoding="utf-8")

    # 3. Save raw JSON metrics
    (RESULTS_DIR / "gateway_comparison.json").write_text(
        json.dumps(metrics_list, indent=2), encoding="utf-8"
    )
    print(f"Benchmark reports generated and written to {RESULTS_DIR}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sentinel Gateway Benchmark Runner")
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Filter models to evaluate (matches substring of provider/model)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of attacks and benign questions to evaluate",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=3,
        help="Number of repetitions per attack case (default: 3)",
    )
    args = parser.parse_args()

    attacks_dev = load_attacks(EVALS_DIR / "attacks_dev.jsonl")
    benign_questions = load_questions(EVALS_DIR / "questions.jsonl")

    if args.limit is not None and args.limit > 0:
        attacks_dev = attacks_dev[: args.limit]
        benign_questions = benign_questions[: args.limit]
        print(f"Limiting benchmark to {len(attacks_dev)} attacks and {len(benign_questions)} questions.")

    models_to_run = MODELS_TO_EVALUATE
    if args.model:
        query = args.model.lower()
        models_to_run = [
            m for m in MODELS_TO_EVALUATE if query in f"{m.provider}/{m.model}".lower()
        ]
        if not models_to_run:
            print(f"Error: No models matched query '{args.model}'. Available models:")
            for m in MODELS_TO_EVALUATE:
                print(f"  - {m.provider}/{m.model}")
            return 1
        print(f"Filtered models to: {[f'{m.provider}/{m.model}' for m in models_to_run]}")

    completed_runs = load_completed_runs()
    if completed_runs:
        print(f"Loaded {len(completed_runs)} previously completed runs from {RAW_RESULTS_FILE}")

    # Sentinel Gateway with Classifier ON
    gateway = SentinelGateway(use_classifier=True)
    metrics_list = []

    for entry in models_to_run:
        m_res = evaluate_model_on_suite(
            entry=entry,
            attacks=attacks_dev,
            questions=benign_questions,
            gateway=gateway,
            repetitions=args.repetitions,
            completed_runs=completed_runs,
        )
        metrics_list.append(m_res)

    write_reports(metrics_list)
    return 0


if __name__ == "__main__":
    sys.exit(main())
