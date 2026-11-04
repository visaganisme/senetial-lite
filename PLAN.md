# Sentinel Lite — Plan

MCP-native, guardrailed technical-document assistant answering questions over `./docs` with citations.
Also a test bed showing how LangChain, LangGraph, RAG, a vector DB, MCP, an agent harness and
guardrails fit together, with per-role model routing.

## Current environment (verified 2026-11-04)

| Item | Status |
|---|---|
| Python | 3.14.6 on PATH. Target is **3.12** via `uv` — needs `uv` installed (`pip install uv` or winget) and pins in `pyproject.toml` (`requires-python = ">=3.12,<3.13"`). |
| Repo | Git repo, empty except `.env` (never committed), `.gitignore`. |
| `./docs` | **Empty.** Phases 2–3 need documents. Either you drop files in (PDF/MD: datasheets, manuals, standards) or I generate a small synthetic corpus (~8–10 realistic engineering docs across PDF/Markdown with tables, sections, cross-references, plus one doc containing a poisoned "indirect injection" payload for Phase 6). I will draft the corpus for your review if docs are still empty at Phase 1 end. |

## Provider facts (verified against docs; to be re-verified per phase)

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
| groq `llama-prompt-guard-2-86m` (injection_guard) | classify: benign 0.0004, injection 0.9995 (clean separation) | 169 ms |
| groq `llama-prompt-guard-2-22m` (injection_guard) | classify: benign 0.0006, injection 0.9990 | 135 ms |
| groq `openai/gpt-oss-safeguard-20b` (safety_guard) | reachable; behaves as a safe-completion chat model, not a label classifier → Phase 6 wraps it in a classification-verification pass | 420 ms |
| cohere `embed-v5.0-pro` | dims 2048 | 727 ms |
| cohere `embed-v4.0` | dims 1536 | 755 ms |
| cohere `rerank-v5.0-pro` / `rerank-v4.0-pro` | both return correct top result (Washington D.C.) | 479/480 ms |

**Failing (not code-side fixable):**

1. **All Cloudflare calls return 401 "Authentication error"** — chat via the `/ai/v1` OpenAI-compatible endpoint *and* embeddings via the documented REST `/ai/run/{model}` path. The request shape is correct per CF docs, so the token almost certainly lacks **Workers AI** permission (or is the wrong token type). → User action: create/regenerate the API token with Workers AI edit permission. Until then every `cloudflare` chain entry is auto-fallback poison; they stay in `models.yaml` (the router skips them fast) but should be considered inactive.
2. **openrouter `google/gemma-4-31b-it:free`** — basic reply worked once, then HTTP 429 on subsequent calls → free-tier rate friction exactly as the instructions warned. It stays in the answer chain at the bottom; the fallback machinery handles it. The probe rate-limiter spends 6 s spacing on OpenRouter; real runs will face the same friction and drain to the next model quickly.
3. **openrouter `nvidia/nemotron-3.5-content-safety:free`** — HTTP 404 from the provider; id not served. Kept in `models.yaml` per instruction until you (user) confirm replacement; it is effectively dead weight for the safety_guard chain (the groq entry covers the role).

`models.yaml` diff proposal from the probe: the generated order proposal equals the current file order (both failing entries are already last in their chains), so **no permanent change is needed now**; the demotion proposal is stored in `results/model_probe.json` and can be re-applied by re-running the probe at any time.

- **Cohere** — chat models confirmed live: `command-a-plus-05-2026`, `command-a-reasoning-08-2025`, `command-r7b-12-2024`. Embeddings verified callable: `embed-v5.0-pro` (2048-d) and `embed-v4.0` (1536-d). Rerank verified: `rerank-v5.0-pro`, `rerank-v4.0-pro` (ground-truth-correct reranking result). Free-tier rate limits from the `docs.cohere.com/v2/docs/rate-limits` page feed the central limiter.
- **Cloudflare Workers AI** — REST format from docs confirmed as `POST https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/{model}`; embeddings ids `@cf/baai/bge-large-en-v1.5` (1024-d), `@cf/baai/bge-m3` still listed in docs, but the account is 401-blocked (above) so they could not be validated.
- **Groq / OpenRouter** — OpenAI-compatible endpoints; exact IDs re-verified live in the phase-1 probe (table above).

## Architecture

```
                       ┌────────────────────────────────────────────────┐
models.yaml ───────────►  ROLE ROUTER (Phase 1)                          │
  roles + fallback     │  provider call adapters (groq/cohere/cf/OR)    │
  chains               │  central rate limiter • backoff+jitter         │
                       │  on-disk cache • circuit breaker (3→skip 10m)  │
                       └───┬───────────────┬───────────────┬────────────┘
                           │ answer/judge/ │ cheap         │ injection/safety guard
                           ▼               ▼               ▼
┌──────────────────┐   ┌───────────────────────────┐   ┌────────────────┐
│ INGEST (Ph 2)    │   │ LANGGRAPH AGENT (Ph 5)    │   │ GUARDRAILS(Ph 6)│
│ parse→chunk→     │   │ route→retrieve→call_tool  │   │ input /retrieval│
│ embed→Chroma     │   │ →draft→verify→finish      │   │ /tool/output    │
│ access_label meta│   │ state+budgets+checkpoints │   │ allow/block/…   │
└────────┬─────────┘   └────────────┬──────────────┘   └───────┬────────┘
         │                          │                          │
         ▼                          ▼                          ▼
   Chroma (local)          MCP servers (Ph 4):             eval suites + JSONL
   hybrid BM25+vector,      docs_search / eng_calc /       audit log
   rerank (Cohere→CF)       notes_tasks (approval-gated)
                           ┌───────────────────────────┐
evals (Ph 3) ─────────────►EVALS + SHOOT-OUT (Ph 3/8)     │
results/ baselines,         recall@k, MRR, faithfulness,  │
results/model_comparison.md block rate / false-positive rate│
```

(Diagram grows a mermaid version in `README.md` at Phase 7.)

## File layout (target)

```
sentinel/
  pyproject.toml             uv + ruff + pytest config; deps w/ justification
  models.yaml                role → ordered {provider, model, capabilities} chains
  .env.example               COHERE_API_KEY, CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID,
                             OPENROUTER_API_KEY, GROQ_API_KEY
  .gitignore                 excludes .env, .venv, cache/, results/raw/, *.db
  sentinel/
    config.py                Pydantic settings; loads .env + models.yaml (no secrets printed)
    router/                  role router, per-provider adapters, limiter, breaker, cache, call log
    ingest/                  parse(PDF/MD)→clean→chunk(2 strategies)→embed→Chroma
    retrieval/               hybrid search, rerank, access filter, threshold
    guards/                  injection_guard, safety_guard, rules, PII, injection quarantine
    agent/                   LangGraph graph: route/retrieve/call_tool/draft/verify/finish
    mcp_servers/             docs_search, eng_calc, notes_tasks (official MCP Python SDK)
    app/                     CLI (`python -m sentinel ask`), FastAPI + minimal web page
    audit/                   JSONL audit-log writer
  scripts/                   probe_models.py, compare_chunking.py, ...
  evals/ questions.jsonl attacks.jsonl
  results/                   model_probe.json, baselines, model_comparison.md
  tests/                     unit + guardrail + agent tests (pytest, no network where possible)
  docs/                      your documents (empty today)
  README.md docs/threat_model.md
```

## Key decisions

1. **uv + Python 3.12**, pinned. Ruff + pytest wired in `pyproject.toml`.
2. **Direct provider calls / OpenAI-compat** for Groq, Cloudflare, OpenRouter (`langchain-openai` with custom `base_url`, one class each); **`langchain-cohere`** for Cohere chat/embeddings/rerank. Justifications: exact model control and a single `base_url` override beat per-vendor SDKs except where a vendor needs its own (Cohere).
3. **One central rate limiter per provider** (token-bucket keyed by provider, sizes set from each provider's documented free tier), **exponential backoff + jitter**, **sqlite/backoff-free on-disk response cache** keyed by `(provider, model, prompt-hash, params)`, per-run **token + step budget enforced in the router and graph**, all exceptions → next chain entry; 3 consecutive failures → circuit open 10 min. Every call logged: provider, model, latency, token counts.
4. **Vector DB: Chroma** (`chromadb` persistent, local, zero server). Justified as the lowest-friction embedded option for a folder-scale corpus; `lancedb` swap only if Chroma fights us.
5. **Chunking**: heuristic structure-aware splitter (headings/tables/page breaks via PDF text layout) vs `RecursiveCharacterTextSplitter` baseline — compared in Phase 2, reported recall@k/MRR, winner becomes default.
6. **Embedding comparison**: Cohere embed vs `@cf/baai/bge-large-en-v1.5` on the same chunks and eval set; separate Chroma collections to avoid cross-embedding-space errors.
7. **Model ids**: only explicit ids, always probe-checked. Probe auto-demotes any `answer`-chain model failing tool-calling and writes `results/model_probe.json`; you see the diff before I change `models.yaml` permanently.
8. **No frameworks for guardrails** — four small, pure-Python, independently testable layers returning `allow/block/rewrite/escalate` + reason.
9. **Minimal deps** (each justified in a line): `langchain-core`, `langchain-cohere` (Cohere integration + rerank), `langchain-openai` (OpenAI-compat endpoints), `langgraph` (stateful graph + checkpoints), `chromadb`, `pydantic`, `python-dotenv` (or stdlib `.env` parsing — prefer stdlib), `pypdf` (PDF text), `httpx` (HTTP with timeouts), `click` (CLI), `fastapi` + `uvicorn` (Phase 7 only), `pytest`, `ruff`. `mcp` (official SDK) at Phase 4 only. Anything beyond that is a "justify or drop" conversation.

## Phase plan & exit criteria

| Phase | Deliverable | Exit |
|---|---|---|
| 0 (now) | `PLAN.md`, `AGENTS.md` | your approval |
| 1 | router + `models.yaml` + limiter/breaker/cache + `scripts/probe_models.py` → `results/model_probe.json`; chains fixed to models that actually work | pytest green (router fallback, breaker, demotion logic tested offline w/ fakes); probe results shown; commit; pause |
| 2 | ingest + Chroma + hybrid retrieval + rerank + threshold; chunking × embedding comparison report | recall@k / MRR table shown; commit; pause |
| 3 | `evals/questions.jsonl` (40+ questions drafted with you) + eval harness + `make eval` + baselines in `results/` | table shown + 10 judge spot-checks with you; commit; pause |
| 4 | 3 MCP servers + registration + external-client proof (e.g. MCP Filesystem-style client or script using `mcp` client) | inspector + external call demo shown; commit; pause |
| 5 | LangGraph agent w/ budgets, checkpoints, HITL pause/resume, streaming trace; agent evals | forced-failure recovery + step/budget tests green; commit; pause |
| 6 | 4 guardrail layers + `evals/attacks.jsonl` (30+ attacks) + normal set; block-rate / false-positive report | you spot-check false positives; commit; pause |
| 7 | CLI + FastAPI streaming + web page + JSONL audit log | end-to-end demo; README w/ mermaid; commit; pause |
| 8 | shoot-out: ≥3 candidates/role (small + large each) → `results/model_comparison.md`; `models.yaml` updated | comparison table you can act on |

Every phase ends with **tests → report → commit → stop for your go-ahead**.

## Open questions for you

1. **docs/ is empty** — do you have files to drop in, or shall I generate the synthetic engineering corpus (and a poisoned one) for your review?
2. **uv is missing** — OK to install it (`pip install uv`) and pin Python 3.12?
3. For Phase 4, register the 3 MCP servers in **this workspace's** opencode config, or ship an example config + instructions?
4. `notes_tasks`' write target: files under `D:\sentinel\notes\` (git-tracked) as the write surface — acceptable?
