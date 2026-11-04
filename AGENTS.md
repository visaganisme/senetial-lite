# AGENTS.md — Rules for every agent working on Sentinel Lite

These rules are binding for the whole project. Where they conflict with speed, the rules win.

## Scope & role
Project: "Sentinel Lite" — a guardrailed, MCP-native technical-document assistant (RAG over
`./docs` with citations), built phase-by-phase as a showcase of LangChain + LangGraph + vector
DB + MCP + guardrails + per-role model routing. The phase plan lives in `PLAN.md`.

## Secrets
- Keys live only in `.env`: `COHERE_API_KEY`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`,
  `OPENROUTER_API_KEY`, `GROQ_API_KEY`.
- Never print, log, echo, commit, or hardcode them. `.gitignore` must exclude `.env`
  (and `.venv`, `cache/`, local DB files). `.env.example` lists the variable names only.
- If a key ever leaks into output, a file, or git history: stop and tell the user immediately.

## Providers
- The app calls providers directly with these keys; it does not read opencode's own config.
- **Check each provider's current docs before coding against it**: endpoints, exact model ids,
  embedding/rerank model names, free-tier limits. Never guess. Record what was verified and when.
- Use **exact model ids only** — no `~latest`, no aliases, no "auto" routing — so runs are reproducible.

## Tooling
- Python **3.12** via **uv**; run everything through `uv run` / `uv sync` in the project venv.
- **Pydantic** models for every schema (config, document, chunk, tool args/outputs, audit events).
- **ruff** for lint/format; **pytest** for tests; run both before declaring a phase done.
- Prefer the standard library and small functions. Every new dependency needs a one-line
  justification in `pyproject.toml`/`PLAN.md` (or it gets removed).
- Keep code minimal: no premature abstractions, no boilerplate, no framework layers beyond
  LangChain/LangGraph where a plain function is enough.

## Free-tier survival
- One central rate limiter per provider; sizes set from each provider's documented free tier.
- Exponential backoff with jitter; on-disk response cache; per-run token and step caps.
- Never loop endlessly: every loop has a max-iteration / wall-clock bound.
- Log which model actually answered each request (provider, model, latency, tokens).

## Process
- Work in phases per `PLAN.md`. After each phase: run tests/evals, show the results,
  **commit**, then stop and wait for the user's go-ahead. Do not start the next phase early.
- First deliverables of every phase that touches a new provider: doc verification notes.
- `PLAN.md` and `AGENTS.md` are living documents — keep them current when decisions change.
- The user reviews: models.yaml changes, eval-set drafts, guardrail false positives, judge
  spot-checks, and anything in `results/`.

## Working tree
- Only touch files in this project. Treat existing files as user work: investigate before
  modifying; never delete or overwrite anything without a reason stated up front.
- `./docs` contents are read-only inputs for the assistant.
- **NEVER run `ruff --fix` (or any file edit) while a comparison or probe run is in progress.**
  Runs get moved to the background and finish when they finish; code changes wait for them.
  Any result table must be verified non-trivially (illogical numbers e.g. all-zero recall
  against a known-good manual query mean instrumentation bug, not reality) before reporting.
