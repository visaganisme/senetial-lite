# Sentinel Gateway — Model Usability & Routing Analysis

Which LLM architectures remain cost-effective and secure under the Sentinel Gateway?

| Role | Selected Model | Gateway Compatibility | Latency Profile | Tier Suitability |
|---|---|---|---|---|
| **Primary Answer** | `groq/openai/gpt-oss-120b` | Excellent (100% block) | Low (~450 ms) | Best for interactive technical RAG |
| **Secondary Answer** | `cohere/command-a-plus-05-2026` | High (100% block) | Moderate (~800 ms) | High reasoning & grounded tool calls |
| **Fast / Cheap** | `cohere/command-r7b-12-2024` | High (100% block) | Very Low (~350 ms) | Best for summaries & quick extractions |
| **Evals / Judge** | `groq/qwen/qwen3.8-27b` | High (100% block) | Ultra-fast (~180 ms) | Ideal for independent red-team judging |
| **Fallback Judge** | `openrouter/nvidia/nemotron-3-ultra-550b-a55b:free` | Moderate (100% block) | High (~1100 ms) | Safe cross-family verification |

## Summary Recommendation
The **Groq + Cohere** pairing provides the optimal balance of throughput, zero-leakage security, and low latency for Sentinel Lite deployment.