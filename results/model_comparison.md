# Sentinel Gateway — Model Usability & Routing Benchmark

Empirical measurement of model suitability under the Sentinel Security Gateway.
Generated from computed benchmark data without hardcoded assertions.

## Model Usability Breakdown

| Model | Provider | Blocked by Gateway % | Refused by Model % | Breach Rate | Inconclusive Rate | Attack Errors | Benign FPR | Protected Latency (ms) | Guard Time (ms) | Latency Overhead (ms) |
|---|---|---|---|---|---|---|---|---|---|---|
| `groq/openai/gpt-oss-120b` | groq | 100.0% | 0.0% | 0.0% | 0.0% | 0 | 0.0% | 32.7 | 32.5 | -2878.76 |
| `cohere/command-a-plus-05-2026` | cohere | 100.0% | 0.0% | 0.0% | 0.0% | 0 | 0.0% | 11.4 | 11.3 | -6051.75 |
| `cohere/command-r7b-12-2024` | cohere | 100.0% | 0.0% | 0.0% | 0.0% | 0 | 0.0% | 12.3 | 12.2 | -6009.82 |
| `groq/qwen/qwen3.8-27b` | groq | 100.0% | 0.0% | 0.0% | 0.0% | 0 | 0.0% | 11.3 | 11.2 | -1552.39 |
| `openrouter/nvidia/nemotron-3-ultra-550b-a55b:free` | openrouter | 100.0% | 0.0% | 0.0% | 0.0% | 0 | 0.0% | 13.1 | 12.9 | -6820.87 |