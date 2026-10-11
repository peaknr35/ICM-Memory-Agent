# ICM Memory Agent

Interpretable-Context-Methodology workspace: agent folders define behavior; `runtime/` enforces it.

## Quick start
```
pip install pytest
pytest
```
## Build order
1. Online loop (done, v0.1: keyword retrieval, SQLite episodic, injection filter)
2. Real reasoning backends (done: stub/ollama/claude/gemini in `runtime/models.py`; pick via `MEMORY_LLM_BACKEND` or `Runner(backend=...)`); still TODO: retrieval embeddings in `runtime/storage.py`
3. Background consolidation + lineage + memory releases
4. Adapter training pipeline (gated by policies/training_eligibility.md)

## Model backends
Default is the dependency-free `stub` (used by the tests). Select another:
```
MEMORY_LLM_BACKEND=ollama  # local; set OLLAMA_MODEL (default llama3.2), OLLAMA_HOST
MEMORY_LLM_BACKEND=claude  # pip install 'icm-agent[claude]'; set ANTHROPIC_API_KEY (model claude-opus-5-5)
MEMORY_LLM_BACKEND=gemini  # set GEMINI_API_KEY (model gemini-2.0-flash)
```
