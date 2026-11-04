"""Run red-team attack evaluation against the unprotected victim agent (Phase 5).
Produces results/baseline_redteam.json.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sentinel.agent.graph import run_agent
from sentinel.redteam.runner import load_attacks, run_attack_suite
from sentinel.router.router import Runtime

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"
EVALS_DIR = Path(__file__).resolve().parents[1] / "evals"


def main() -> int:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    attacks_file = EVALS_DIR / "attacks_dev.jsonl"
    attacks = load_attacks(attacks_file)

    # Use first 15 representative attacks for the fast baseline run if specified, or all
    fast_mode = "--all" not in sys.argv
    test_set = attacks[:15] if fast_mode else attacks
    print(f"Running baseline red-team sweep ({len(test_set)} attacks, mode: UNPROTECTED)...")

    runtime = Runtime.load()
    target_model = (
        runtime.config.roles["answer"][0].model if runtime.config.roles.get("answer") else "default"
    )

    def agent_invoker(payload: str, mode: str):
        state = run_agent(payload, gateway_mode="off", runtime=runtime, max_steps=4)
        tool_names = [f"call:{t.get('tool')}" for t in state.tool_trace]
        return state.final_answer, tool_names, None, state.latency_ms, state.tokens_used

    results, summary = run_attack_suite(
        attacks=test_set,
        model_id=target_model,
        mode="unprotected",
        invoker_fn=agent_invoker,
        repetitions=1 if fast_mode else 3,
        split_name="dev",
    )

    out_file = RESULTS_DIR / "baseline_redteam.json"
    payload = {
        "summary": summary.model_dump(),
        "results": [r.model_dump() for r in results],
    }
    out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"Baseline run complete! Breach rate: {summary.overall_breach_rate * 100:.1f}%, Saved to -> {out_file}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
