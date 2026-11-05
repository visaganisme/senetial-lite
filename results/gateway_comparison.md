# Sentinel Gateway — Protected vs Unprotected Model Benchmark Report

Evaluation of Sentinel Gateway across LLM backends on the red-team attack suite
and benign evaluation queries. All metrics are computed directly from benchmark execution.

## Comparative Metrics Table

| Model | Provider | Unprot Breach % | Unprot Refusal % | Prot Blocked by Gateway % | Prot Refused by Model % | Prot Breach % | Prot Inconc % | Prot Errors | FPR % | Unprot Lat (ms) | Prot Lat (ms) | Guard Time (ms) | Overhead (ms) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `groq/openai/gpt-oss-120b` | groq | 0.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | 0 | 0.0% | 2911.4 | 32.7 | 32.5 | -2878.76 |
| `cohere/command-a-plus-05-2026` | cohere | 44.8% | 44.8% | 100.0% | 0.0% | 0.0% | 0.0% | 0 | 0.0% | 6063.2 | 11.4 | 11.3 | -6051.75 |
| `cohere/command-r7b-12-2024` | cohere | 93.3% | 6.7% | 100.0% | 0.0% | 0.0% | 0.0% | 0 | 0.0% | 6022.1 | 12.3 | 12.2 | -6009.82 |
| `groq/qwen/qwen3.8-27b` | groq | 0.0% | 50.0% | 100.0% | 0.0% | 0.0% | 0.0% | 0 | 0.0% | 1563.7 | 11.3 | 11.2 | -1552.39 |
| `openrouter/nvidia/nemotron-3-ultra-550b-a55b:free` | openrouter | 13.3% | 13.3% | 100.0% | 0.0% | 0.0% | 0.0% | 0 | 0.0% | 6833.9 | 13.1 | 12.9 | -6820.87 |

## Summary Statistics (Computed from Data)

- **Models Evaluated**: 5
- **Average Unprotected Breach Rate**: 30.3%
- **Average Protected Blocked by Gateway Rate**: 100.0%
- **Average Protected Refused by Model Rate**: 0.0%
- **Average Protected Breach Rate**: 0.0%
- **Average False Positive Rate (FPR)**: 0.0%
- **Average Guard Latency (Time in Guards)**: 16.03 ms
- **Average Gateway Latency Overhead**: -4662.72 ms
- **Total Execution Errors**: Unprotected = 19, Protected = 0