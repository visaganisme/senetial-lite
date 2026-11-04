# Sentinel — Plan

**Project: Sentinel — a security gateway for AI agents.** The RAG + MCP technical-document
assistant from Phases 1–3 is retained as the **victim app**: a realistic agent with document
retrieval, calculation tools, and write tools whose insecurity is what the gateway defends
against. The **main deliverable is the gateway**: an enforcement layer that sits between an
agent and its tools/LMs and enforces injection scanning, tool allowlists, argument validation,
human approval for writes, and budgets — plus a **red-team suite of 100+ attacks** and a
**comparison report of unprotected vs protected agents across ≥5 models** with block rate,
false-positive rate, and latency overhead.

Everything completed so far is kept as-is (phase-1 router, limiter, breaker, cache, probe).
The victim app deliberately has the same shapes it would have had without the project pivot:
standard LangChain/LangGraph calls and MCP tool invocations, so the gateway wraps *real* seams.

## Threat model (one paragraph; full version lands in `docs/threat_model.md`)

An attacker controls **content the agent will read** (documents, PDFs, tool results) and
**chat input**, and wants the agent to: follow injected instructions, call disallowed or
dangerous tools (writes, notes-as-data-channels), exfiltrate data into tool arguments or
strings it would otherwise echo, or burn tokens/loops until quota dies. The gateway assumes
the agent's LLM can be talked into anything and gives the model no direct tool access:
every tool call and every model call passes through policy.

## Current environment (verified 2026-11-04)

| Item | Status |
|---|---|
| Python | 3.12.16 project venv via `uv` (global Python untouched); `uv sync`/`uv run` workflow. |
| Repo | Phase 1 committed (`bb7871a`): router + limiter + breaker + cache + call log + probe + 21 offline tests. |
| `./docs` | Still empty — user will add real PDFs; synthetic corpus goes into a **separate `./docs_synthetic`** (incl. one poisoned PDF), both reviewed before use. |
| Cloudflare | **Token fixed 2026-11-04** (embeddings verified live in the Phase-2 build); chat/guard ids get a formal re-probe at Phase 5/6. |

## Phase 2 results (2026-11-04, seed set: 17 questions over `docs_synthetic`, 9 docs, `internal` access, Cohere rerank chain)

| arm (chunking × embedding) | recall@1 | recall@3 | recall@5 | MRR@10 | refusal* |
|---|---|---|---|---|---|
| structure × cohere embed-v5.0-pro | **0.643** | **1.000** | **1.000** | **0.821** | 0.60 |
| structure × cohere embed-v4.0 | 0.643 | 1.000 | 1.000 | 0.821 | 0.60 |
| structure × cf bge-large-en-v1.5 | 0.643 | 1.000 | 1.000 | 0.821 | 0.60 |
| recursive × cohere embed-v5.0-pro | 0.500 | 0.571 | 0.571 | 0.524 | 0.67 |
| recursive × cohere embed-v4.0 | 0.500 | 0.571 | 0.571 | 0.524 | 0.67 |
| recursive × cf bge-large-en-v1.5 | 0.500 | 0.571 | 0.571 | 0.524 | 0.67 |

Findings & caveats (honest):
1. **Chunking dominates; embedding choice is a wash.** Structure-aware chunking beats recursive
   everywhere (+0.14 recall@1, +0.08 MRR). With the same chunks + the rerank chain, all three
   embedders produced identical ranked outcomes — differences only show without rerank or on a
   larger corpus. `structure × cohere embed-v5.0-pro` is the default going forward.
2. **Rerank scoring previously fell back to RRF silently under free-tier 429s** — now the
   rerank path paces through the central limiter, is cached, and reports `rerank_health`
   per arm; the table above is real Cohere rerank scoring.
3. **Refusal threshold collision:** answerable top-scores 0.279–0.781 vs unanswerable
   0.095–0.329 overlap (S08 0.322 vs S17 0.329) — a pure threshold cut caps refusal precision
   at ~0.67 on this set (default 0.35 keeps 3/3 true refusals, cost: 2 false refusals).
   Phase 3 tunes thresholds against the dev set only — larger question set may separate better.
4. The poisoned doc QA-VX-7 appears in top-5 for related-but-ignorant queries (internal users);
   expected — quarantining is the Phase-6 gateway's job, not retrieval's.

## Provider facts (verified against docs; re-verified per phase)

### Phase 1 live probe results (2026-11-04, on the user's real keys — `results/model_probe.json`)

**Working (probe status ok):**

| Role chain entry | Verified capabilities | Latency (first call) |
|---|---|---|
| groq `openai/gpt-oss-120b` (answer) | chat, structured JSON, tool calling | 625 ms basic / 418 ms tools |
| cohere `command-a-plus-05-2026` (answer) | chat, structured JSON, tool calling | 1089 ms basic |
| cohere `command-a-reasoning-08-2025` (judge) | chat, structured JSON | 601 ms |
| groq `qwen/qwen3.8-27b` (judge) | chat, structured JSON, tool calling | 129 ms |
| openrouter `nvidia/nemotron-3-ultra-550b-a55b:free` (judge) | chat, structured JSON | 1120 ms |
| cohere `command-r7b-12-2024` (cheap) | chat, structured JSON | 537 ms |
| groq `llama-prompt-guard-2-86m` (injection_guard) | classify: benign 0.0004, injection 0.9995 | 169 ms |
| groq `llama-prompt-guard-2-22m` (injection_guard) | classify: benign 0.0006, injection 0.9990 | 135 ms |
| groq `openai/gpt-oss-safeguard-20b` (safety_guard) | reachable; safe-completion chat style, not a label classifier → gateway wraps it in a classification-verification pass | 420 ms |
| cohere `embed-v5.0-pro` | dims 2048 | 727 ms |
| cohere `embed-v4.0` | dims 1536 | 755 ms |
| cohere `rerank-v5.0-pro` / `rerank-v4.0-pro` | both return correct top result | 479/480 ms |

**Failing (not code-side fixable):**

1. ~~All Cloudflare calls return 401~~ — **resolved 2026-11-04 during Phase 2**: after the user
   regenerated the token, all Cloudflare arms (chat test earlier + `@cf/baai/bge-large-en-v1.5`
   embedding builds) succeed on the new token. CF is re-enabled as the embeddings comparison
   and fallback provider. A formal re-probe of the other CF chat/guard ids happens at Phase 5/6.
2. **openrouter `google/gemma-4-31b-it:free`** — 429 free-tier friction on repeat calls; kept
   last in the answer chain; fallback machinery handles it.
3. **openrouter `nvidia/nemotron-3.5-content-safety:free`** — HTTP 404; id not served. Kept
   in `models.yaml` per instruction; Phase 8 (user-approved) will pick the next best safety id.

`models.yaml` demotion proposal is stored in `results/model_probe.json`; current file order
already matches it, so no permanent change was applied.

- **Cohere** — chat `command-a-plus-05-2026`, `command-a-reasoning-08-2025`, `command-r7b-12-2024`; embed `embed-v5.0-pro` (2048-d), `embed-v4.0` (1536-d); rerank `rerank-v5.0-pro`, `rerank-v4.0-pro`. Free-tier rate limits: `docs.cohere.com/v2/docs/rate-limits`.
- **Cloudflare Workers AI** — request shape confirmed from docs; token regenerated and working
  since 2026-11-04 (embeddings verified live, `@cf/baai/bge-large-en-v1.5` built all Phase-2 arms).
  Chat/guard ids (`@cf/meta/llama-guard-3-8b` etc.) get a formal re-probe at Phase 5/6.
- **Groq / OpenRouter** — OpenAI-compatible endpoints; exact ids re-verified live (table above).

## Architecture (pivot)

```
                    ┌─────────────────────────────────────────────┐
models.yaml ────────► RFC: ROLE ROUTER (Ph 1, done)               │
                    │ limiter • backoff • cache • breaker • log   │
                    └──────┬──────────────────────┬───────────────┘
                           │                      │
             ┌─────────────▼───────────┐  ┌───────▼──────────────────────┐
             │ VICTIM AGENT (Ph 4-5)   │  │ SENTINEL GATEWAY (Ph 6, main)│
             │ LangGraph RAG + MCP     │  │ input guard  (injection+PII) │
             │ docs_search / eng_calc  │  │ retrieval guard (score, ACL, │
             │ notes_tasks (writes)    │  │   quarantine poisoned chunks)│
             │ "gateway: OFF" run mode │  │ tool guard (allowlist,      │
             └─────────┬───────────────┘  │   Pydantic args, approval,   │
                       │                  │   budgets)                   │
                       │   every model &  │ output guard (citation check,│
                       │   tool call      │   safety, no leakage)        │
                       └──── interposed ──►│ + JSONL audit log            │
                                           └──────┬───────────────────────┘
  Ph 2: RAG corpus/vector DB for the victim (docs + docs_synthetic, PoC PDF is corpus)
  Ph 3: RED-TEAM SUITE — 100+ attacks in evals/attacks.jsonl (direct injection,
        poisoned PDF, tool abuse, exfiltration, token-burn loops) + benign set (FPR)
  Ph 7-8: dashboard + side-by-side demo + unprotected vs protected over ≥5 models
        (block rate, false-positive rate, latency overhead) → results/
```

The gateway is an **interposable layer, not a rewrite**: the victim agent calls gateway
functions (`gw.pass_input`, `gw.pass_retrieval`, `gw.check_tool`, `gw.pass_output`) that are
trivially no-ops when `gateway: off`, so the same agent graph runs for both arms of every
comparison. Turn-level decisions: `allow / block / rewrite / escalate` + reason, always logged.

## File layout (target, unchanged parts kept)

```
sentinel-lite/                   (repo root D:\sentinel)
  pyproject.toml models.yaml .env.example .gitignore      # done, phase 1
  sentinel/
    config.py                                            # done
    router/                                              # done (Ph 1)
    ingest/ retrieval/                                    # Ph 2 victim RAG
    mcp_servers/  docs_search, eng_calc, notes_tasks       # Ph 4 victim tools
    agent/        LangGraph victim graph (route/retrieve/call_tool/draft/finish)
    gateway/      input / retrieval / tool / output guards + audit writer  # Ph 6 (main)
    dashboard/    FastAPI + web page: side-by-side demo & red-team report viewer # Ph 7
    redteam/      attack runner + scorers (block rate, FPR, latency overhead)   # Ph 3/8
  evals/ questions.jsonl attacks.jsonl          # Ph 3: 100+ attacks + benign set
  results/ baselines, model_probe.json, gateway_comparison.md, model_comparison.md
  docs/docs_synthetic/                          # real docs vs synthetic corpus
  README.md docs/threat_model.md
```

## Key decisions (delta from phase-1 state; existing decisions unchanged)

1. **Gateway as functions, not a framework.** No guardrail library. Each guard is a pure
   function `Decision(allow|block|rewrite|escalate, reason, modified_payload?)`, independently
   testable, and composable. `AGENTS.md` already bans frameworks here.
2. **Same agent binary, two modes.** `gateway: on|off` is runtime config, not a code fork —
   the unprotected arm of the comparison is the *real* victim, not a strawman.
3. **Attack corpus is versioned data, not scripts.** `evals/attacks.jsonl` rows carry
   category, payload, target_role, expected gateway behavior, and source-of-truth for the score.
4. **Red-team runner reuse of Phase 1 machinery.** Attacks run through the same router
   (limiter/breaker/cache/budgets), so a 100+ attack sweep across 5 models stays inside free tiers.
5. **Write approval is a gateway property, not an agent convention.** `notes_tasks` stays
   exactly as unsafe as any raw MCP write tool; the gateway's tool guard is what gates it.
   Write target remains `D:\sentinel\notes\` (git-ignored, path-jail enforced by the tool).
6. **Metrics model:** every attack × model × mode produces one scored event: blocked, allowed
   (bad), false-positive (benign blocked), latency overhead vs the same call unprotected.
7. **Red-team rules (user, 2026-11-04):** (a) the attack suite is split into
   `attacks_dev.jsonl` (~70%) and `attacks_heldout.jsonl` (~30%) — the gateway is tuned against
   dev only; heldout stays unread until the Phase 8 report, which reports both sets separately.
   (b) Every attack runs 3× per (model, mode); results are success-rate-with-spread, never a
   single observation.
8. **Few new deps** this pivot: nothing beyond the current set foreseen; dashboards use
   FastAPI (already planned, Phase 7) and render from the JSONL audit log + results JSONs.

## Phase plan & exit criteria (revised)

| Phase | Deliverable | Exit |
|---|---|---|
| ~~0~~ ~~1~~ | planning, router, probes — done, committed | ✔ done |
| 2 | Victim RAG: ingest → chunk (2 strategies) → embed (Cohere vs CF) → Chroma; hybrid retrieval + rerank + access filter + threshold | recall@k / MRR table shown; commit; pause |
| 3 | **Red-team + eval suite**: `evals/questions.jsonl` benign set (40+, drafted with you) and `evals/attacks.jsonl` — **100+ attacks** across direct injection, poisoned PDF, tool abuse, exfiltration, token-burn loops — plus the attack runner and scorers (expected-behavior labels; runs on unprotected agent) | attack list reviewed by you (esp. any you want added/removed); commit; pause |
| 4 | Victim agent core: RAG answerer + 3 MCP servers (docs_search, eng_calc, notes_tasks) wired to real tools, registered in **this project's** opencode config (exact config change shown before saving) | MCP inspector + external-client proof shown; commit; pause |
| 5 | Victim agent harness: LangGraph graph (route→retrieve→call_tool→draft→finish) with step/token caps as *agent-side* knobs; compiled with `gateway=OFF`; red-team baseline run `unprotected vs attacks.jsonl` → `results/baseline_redteam.json` | baseline block/near-zero shown alongside a issues-review; commit; pause |
| 6 | **THE GATEWAY (main phase)**: four guards (input, retrieval, tool, output) as interposable decisions; injection classifier + rules; poisoned-chunk quarantine; tool allowlist + Pydantic arg validation + write-approval (HITL, exact args shown, resume-on-approve) + per-run budgets; output citation/safety/leakage check; JSONL audit log every decision | unit tests per guard + you spot-check FPs; commit; pause |
| 7 | Dashboard + side-by-side demo: unprotected vs protected runs of the same questions side by side in a minimal local web UI (answer, citations, tool trace, gateway decisions, model-per-step); `make redteam` returns the sweep | demo recorded/run live for you; commit; pause |
| 8 | Report: unprotected vs protected across **≥5 models** from models.yaml (groq gpt-oss-120b, cohere command-a-plus, cohere command-r7b, groq qwen3.8, openrouter nemotron at minimum; one small + one large per family where available) on block rate, false-positive rate, latency overhead; **two reports**: `results/gateway_comparison.md` (per-model) and updated `results/model_comparison.md` (which models stay usable under the gateway) | tables + go/no-go recommendation per model; final commit |

Every phase ends: tests → report → commit → stop for go-ahead.

## Open questions (blocked on you)

1. Cloudflare token Workers-AI permission (carried from Phase 1; unblocks cheap/safety fallbacks).
2. Phase 8's dead-ish openrouter content-safety id: replace with a real id you have seen,
   or let me drop it from `safety_guard` and pick `openrouter`'s next best safety-ish model at Phase 8?
3. Approval interaction for Phase 6/7 writes: CLI prompt for the demo, plus a FastAPI
   approve/deny endpoint for the dashboard — OK?
4. Dashboard scope: single HTML page (no JS build step) over the audit log + results JSONs — OK?
