# PHASE_NOTES — Phase 1: LLM layer & agent contracts

This file is the hand-off note for **Phase 2 (orchestrator rewiring)**. Everything here
reflects the actual code on disk, not the outdated README/DEVELOPER_GUIDE.

---

## 1. New unified agent `execute()` signatures (single Pydantic input model)

Every agent's `execute()` now takes **exactly one** Pydantic input model and returns a
validated output model. The orchestrator must call agents with these models only.

| Agent | Class | `execute()` signature | Returns | Role |
|---|---|---|---|---|
| designer | `GameDesignerAgent` | `execute(input_data: DesignerInput)` | `GameDesignDocument` | `designer` |
| architect | `ArchitectAgent` | `execute(input_data: ArchitectInput)` | `ArchitecturePlan` | `architect` |
| quest_designer | `QuestDesignerAgent` | `execute(input_data: QuestDesignerInput)` | `QuestGraphList` | `quest` |
| dialogue_writer | `DialogueWriterAgent` | `execute(input_data: DialogueWriterInput)` | `DialogueTreeList` | `dialogue` |
| art_director | `ArtDirectorAgent` | `execute(input_data: ArtDirectorInput)` | `AssetPromptsOutput` | `art` |
| prompt_refiner | `PromptRefinerAgent` | `execute(input_data: PromptRefinerInput)` | `PromptUpdates` | `refiner` |
| level_generator | `LevelGeneratorAgent` | `execute(input_data: LevelGeneratorInput)` | `LevelLayout` | `level` |
| localization | `LocalizationManagerAgent` | `execute(input_data: LocalizationInput)` | `LocalizationOutput` | `localization` |
| coder | `CoderAgent` | `execute(input_data: CoderInput)` | `CoderOutput` | `code` |
| qa | `QAAgent` | `execute(input_data: QAInput)` | `QAReport` | `qa` |
| playtester | `AIPlaytesterAgent` | `execute(config: PlaytestConfig)` | `PlaytestReport` | `playtest` |

Notes for Phase 2:

- Input/output wrapper models live in `backend/schemas/agent_schemas.py`:
  `DesignerInput`, `ArchitectInput`, `QuestDesignerInput`, `DialogueWriterInput`,
  `ArtDirectorInput`, `PromptRefinerInput`, `LevelGeneratorInput`,
  `LocalizationInput`, `CoderInput`, `QAInput`, plus the list wrappers
  `QuestGraphList`, `DialogueTreeList`, `PromptUpdates`.
- `WizardInput` has a **single source of truth**:
  `backend/schemas/agent_schemas.py` (`api_schemas.py` re-exports it; the old
  duplicate class in `backend/api/generation.py` was removed). Shape:
  `controls: dict[str, str]`, `text_description: str`, theme/genre/etc.
- Backward-compat shim: `ArchitectAgent.execute` also accepts a bare
  `GameDesignDocument` (it wraps it into `ArchitectInput`). Prefer `ArchitectInput`.
- `BaseAgent` exposes `role` (class attr) used to pick token budgets / models, and
  `_call_llm(prompt, response_model, *, role=None, max_tokens=None, temperature=None)`
  which delegates to `backend/services/llm_client.py`.

## 2. LLM client contract (`backend/services/llm_client.py`)

- Async client supporting **both** backends, selected via `settings.llm_backend`
  (`auto` → OpenAI-compatible if an API key is set, else Ollama):
  - Ollama: `ollama.AsyncClient`, structured output via `format=<json schema>`.
  - OpenAI-compatible: raw `httpx` POST to `{base_url}/chat/completions` with
    `response_format={"type": "json_schema", ...}`.
- Schema repair loop: on JSON/schema validation failure the validation-error text is
  fed back to the model and the request retried, up to
  `settings.llm_max_repair_retries` (default 3) times.
- Timeouts from `settings.llm_timeout_seconds`; configurable max output tokens with
  `DEFAULT_CODE_MAX_TOKENS = 16384` for code roles.
- Module-level singleton: `await get_llm_client()`. Tests/smoke script monkeypatch the
  transport (`ScriptedTransport` in `scripts/agent_smoke.py`, fixtures in
  `tests/conftest.py`) — no server needed.

## 3. Config / env alignment (`backend/core/config.py`, `.env.example`)

- `sd_webui_url` reads `STABLE_DIFFUSION_URL` (alias kept for internal name).
- Unified model env names: `LLM_CODE_MODEL`, `LLM_DESIGN_MODEL`,
  `LLM_EMBEDDING_MODEL`, `LLM_BACKEND`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`,
  `LLM_TIMEOUT_SECONDS`, `LLM_MAX_REPAIR_RETRIES`, `LLM_CODE_MAX_TOKENS`
  (legacy `OLLAMA_*`/`OPENAI_*`/`AGENT_*` names accepted as aliases).
- `WORKSPACE_ROOT` (`workspace_root`) and `GODOT_HEADLESS_PATH`
  (`godot_headless_path`) are settings-driven.
- GPU defaults corrected to the actual hardware: `gpu_model="Radeon 8060S"`,
  `gpu_vram_gb=128.0` (unified memory shared with CPU).
- `requirements.txt`: added `ollama==0.6.1` and `langgraph-checkpoint-postgres==2.0.23`
  (compatible with langgraph 0.2.x / pydantic v2 stack already pinned).

## 4. Out-of-scope fixes that were required to keep the repo importable

These touched files outside Phase 1's nominal scope but were necessary after the
contract unification (recorded here per Rule 1):

- `backend/services/orchestration.py`: stale multi-positional agent call signatures
  updated to construct the new single-model inputs so the module imports and existing
  graph nodes stay consistent. Full LangGraph rewiring remains Phase 2 work.
- `backend/services/billing_service.py`: dict/model mismatch fixed (call sites passed
  plain dicts where pydantic models were expected and vice versa).
- `backend/api/generation.py`: duplicate `WizardInput` definition removed in favour of
  the canonical re-export from `agent_schemas`.
- `backend/services/art_pipeline.py`: minor consistency fix after schema unification.

## 5. Remaining adjacent bugs / TODOs noticed (NOT fixed — other phases' scope)

1. **Orchestrator state flow**: `orchestration.py` still passes whole upstream outputs
   between nodes without pruning; Phase 2 should define the LangGraph state schema
   (checkpointer will use `langgraph-checkpoint-postgres`, now installed).
2. **`playtester` agent**: requires a real Godot headless binary; offline it returns a
   deterministic failure report (`Project path does not exist`). Needs a proper
   skipif/marker strategy and sandbox workspace handling (Godot phase).
3. **`agents/playtester.py` lives at package top level** while all other agents are
   subpackages (`agents/<name>/__init__.py`). Cosmetic inconsistency; move during a
   refactor phase, not alongside feature work.
4. **`GameDesignDocument` optional fields**: `quest_complexity` / `dialogue_depth` were
   added with safe defaults; downstream designers/architect prompts don't yet mention
   them — prompt templates should be updated when quest/dialogue generation is tuned.
5. **Ollama `format=schema` strictness varies by model**; very small models may still
   emit invalid JSON. The repair loop mitigates this, but per-role fallback models
   would be more robust (config hook exists: `llm_backend`/model per role).
6. **`tests/unit/` legacy directory** contains pre-Phase-1 tests that do not exercise
   the new contracts; consolidate or delete in the test-hygiene pass.
7. **README.md / DEVELOPER_GUIDE.md / USER_MANUAL.md / PHASE*_COMPLETION_REPORT.md**
   remain outdated (document features that don't exist). Documentation rewrite pending.

## 6. Verification commands (offline)

```bash
make verify-offline        # == test-offline + smoke-agents
make test-offline          # python -m pytest tests/ -q -p no:libtmux
make smoke-agents          # python scripts/agent_smoke.py  (prints validated outputs)
```

Both require no GPU, no LLM server, no Docker, no network.
