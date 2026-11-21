# PHASE_NOTES — Phase 1: LLM layer & agent contracts

This file is the hand-off note for **Phase 2 (orchestrator rewiring)**. Everything here
reflects the actual code on disk, not the outdated README/DEVELOPER_GUIDE.

---

## 0. Phase 1 close-out audit (2026-11-14)

Re-audited every Phase 1 task against the files on disk; tasks 1–3 and the deps were
already implemented. Completed the remaining gap and hardened alignment:

- **AGENTS.md (task 4)**: created at the repo root with the common system-prompt
  preamble (immutable Core Engine, `module_` signal prefix, closed 10-slot asset
  vocabulary, Godot 4.x GDScript, JSON-only output). `BaseAgent.__init__` now
  prepends it to each agent's role-specific system prompt via
  `backend.agents.base.load_common_preamble()` (cached, HTML comments stripped,
  graceful degradation if the file is missing). New mocked-LLM tests in
  `tests/test_config_and_base_agent.py` cover config/env alignment, the preamble,
  and `BaseAgent._call_llm` returning a validated model through the fake client.
- **config.py**: `llm_max_tokens` / `llm_code_max_tokens` now have explicit
  `LLM_MAX_TOKENS` / `LLM_CODE_MAX_TOKENS` validation aliases (they were silently
  documented-but-unread in `.env.example`). All other prompt items (STABLE_DIFFUSION_URL
  alias, unified `LLM_*` model names, `WORKSPACE_ROOT`, `GODOT_HEADLESS_PATH`,
  Radeon 8060S / 128 GB defaults, 16384 code tokens) verified present.
- **.env.example**: added the missing GPU section (`GPU_VENDOR/GPU_MODEL/GPU_VRAM_GB/
  GPU_BACKEND`) so every Settings field family is discoverable from the template.
- Offline verification confirmed green without GPU/LLM/network: 70 passed
  (`make test-offline`), 11/11 agents produce validated outputs (`make smoke-agents`).

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

---

## Phase 2 — Schema fixes: adjacent bugs noticed (NOT fixed — other phases' scope)

1. **`orchestration._run_architect` reads a non-existent field**: line ~260 builds the
   status message with `len(plan.modules)`, but `ArchitecturePlan`
   (`backend/schemas/agent_schemas.py`) defines `required_modules`, not `modules`.
   The expression raises `AttributeError` inside the node's try-block, so the
   architect step is reported as `"Architect failed: 'ArchitecturePlan' object has no attribute 'modules'"`
   even on successful LLM generation. Fix in the orchestrator phase (use
   `plan.required_modules`).
2. **Divergent duplicate models between schema modules**: `QuestStage` exists in both
   `api_schemas.py` (pattern-validated `type: str`) and `agent_schemas.py`
   (`type: Literal[...]`), and the two are separate classes with subtly different
   validation semantics. Same duplication risk applies to other quest/dialogue
   models. Consolidate to a single source of truth (re-export from `agent_schemas`)
   during the API-hardening phase; until then, cross-module `model_dump()` round-trips
   may validate differently depending on which class is imported.
3. **Legacy root-level test scripts** (`test_phase8_components.py`, `test_phase8_final.py`,
   `test_phase9_components.py`, `test_phase9_standalone.py` at repo root): stale
   Phase 8/9-era standalone scripts that predate the current contracts. They are not
   collected by `pytest tests/` (the offline targets only run `tests/`), but any
   bare `pytest` / IDE "run all tests" invocation collects them and they can fail or
   require live services. Delete or migrate them in the test-hygiene pass.

---

## Phase 3 — Agent contracts: audit & close-out (2026-11-14)

Re-audited every agent package (`backend/agents/*/__init__.py`, plus
`backend/agents/playtester.py`) against the single-model contract.

**Verified invariants (no changes needed):**
- All 11 agents' `execute()` take exactly ONE pydantic input model:
  `DesignerInput`, `ArchitectInput`, `QuestDesignerInput`, `DialogueWriterInput`,
  `ArtDirectorInput`, `PromptRefinerInput`, `LevelGeneratorInput`,
  `LocalizationInput`, `CoderInput`, `QAInput`, `PlaytestConfig`. The
  `test_execute_takes_exactly_one_input_model` parametrized test enforces this.
- `scripts/agent_smoke.py` runs all 11 agents against a mocked transport; added
  `tests/test_agent_smoke_script.py` so the smoke script itself is covered by
  `make test-offline` (subprocess-isolated, skipif-guarded when a real Godot
  binary is present).

**Fix required to make the DONE criterion true (see §4-style note):**
On a machine without the DB stack installed, `python scripts/agent_smoke.py`
failed for 9/11 agents with `ModuleNotFoundError: No module named 'sqlalchemy'`:
`BaseAgent._call_llm` imports `backend.services.llm_client`, which executes
`backend/services/__init__.py`, which eagerly imported `billing_service`
(sqlalchemy + DB models). `backend/services/__init__.py` now uses PEP 562 lazy
`__getattr__`; all explicit import styles keep working. Smoke result after the
fix: 11/11 OK offline; full suite: 110 passed.

**Adjacent bugs noticed (NOT fixed — other phases' scope):**
1. `backend/agents/playtest/__init__.py` is an EMPTY package; nothing imports it
   (everything uses `backend.agents.playtester`). Confirms PHASE_NOTES §5 item 3 —
   consolidate during the refactor phase.
2. Agents hardcode default model names in their `__init__` signatures
   (e.g. `"qwen2.5:32b"`, `"qwen2.5-coder:32b"`) instead of reading
   `settings.llm_*_model`; orchestrator phase should inject models from config.
3. `ArchitectAgent.execute` still accepts a bare `GameDesignDocument` as a
   compat shim (documented in §1 above); remove once the orchestrator is rewired.
4. `QAAgent.execute(QAInput)` is fully deterministic (no LLM call) — fine today,
   but if QA gains LLM checks later, remember it currently bypasses `_call_llm`.
5. `pytest` ≥9 + the preinstalled `libtmux` plugin conflict (`Marks cannot be
   applied to fixtures`); the Makefile offline targets already pass
   `-p no:libtmux`, but a bare `pytest` invocation fails at startup. Consider
   adding `PYTEST_ADDOPTS` or pinning pytest in requirements-dev during the
   test-hygiene pass.

## Phase 4 — Paths + workspace: close-out (2026-11-14)

**What landed:**
- `backend/core/paths.py`: single source of truth for the canonical layout
  `{workspace_root}/{project_id}/godot_project/` (+ `assets/`, `data/`) with a
  sibling staging dir `{workspace}/{project_id}/assets/` and
  `{workspace_root}/exports/`. The old `game_project/` name and hard-coded
  `/workspace/*` roots are gone from all Python consumers (playtester,
  art_pipeline, godot_integrator, api/export, api/generation, api/marketplace,
  marketplace_service). Template resolves to repo-level `godot_core/` via
  `Settings.godot_core_path` (env `GODOT_CORE_PATH`).
- `WorkspaceManager`: root from settings (`WORKSPACE_ROOT`), local git identity
  (`GIT_AUTHOR_NAME`/`GIT_AUTHOR_EMAIL`), real `baseline` tag created at
  workspace init, working `rollback()` (`reset --hard baseline` + `clean -fd`),
  functional snapshot-based `preserve_assets()`/`restore_assets()` with a
  git-ignored `.kotodama_preserved/` dir and `clear_preserved()`.
- `docker-compose.yml`: backend and godot-headless now share ONE named volume
  (`workspace_data` → `/app/workspace` and `/godot/workspace`; the previous
  divergence between bind-mount `./workspace` and named volume was real —
  workers never saw generated projects). Backend gets
  `WORKSPACE_ROOT/GODOT_CORE_PATH/GIT_AUTHOR_*` env; worker gets
  `WORKSPACE_ROOT/GODOT_CORE_PATH`.
- `.env.example`: new WORKSPACE section (`WORKSPACE_ROOT=./workspace`,
  `GODOT_CORE_PATH=./godot_core`, `GIT_AUTHOR_*`); stale
  `WORKSPACE_ROOT=./workspace_instances` in GENERATION SETTINGS removed.
- Tests: `tests/test_workspace_paths.py` (10 tests, fully offline — tmp_path +
  system git only): path-helper consistency, template copy (*.import ignored),
  baseline tag == HEAD after create, rollback reverts dirty edits AND removes
  untracked files, rollback resets branch pointer after `[result]` commits,
  preserve/restore roundtrip survives rollback+clean, cleanup.

**Adjacent bugs noticed (NOT fixed — other phases' scope):**
1. `backend/services/orchestration.py` `_run_retry` (~line 352) calls
   `workspace_manager.preserve_assets()` but NOTHING ever calls
   `restore_assets()`/`clear_preserved()` afterwards — preserved assets sit in
   `.kotodama_preserved/` forever and are never brought back, so generated
   assets are still effectively lost across retries until the orchestrator is
   rewired (fix belongs to the orchestration phase; the manager API + tests are
   ready).
2. `backend/api/export.py` Fastlane path writes export presets/artifacts INTO
   the tracked `godot_project/` tree (contaminates the git baseline; later
   rollbacks delete or revert them). Should write under `paths.exports_dir()`.
3. Marketplace download/delete endpoints remain mocks (`api/marketplace.py`
   fakes success; storage path derived from workspace root but no real upload
   flow) — pre-existing, unchanged by Phase 4.
4. `Settings.workspace_root` default `/app/workspace` is meaningless on bare
   WSL2 runs without docker-compose; acceptable because compose pins it, but a
   relative default would be friendlier (devex phase).

## Phase 5 — Orchestrator wiring

**What was done:**
- `backend/services/orchestration.py` rewritten: `GenerationState` gained
  `asset_prompts`, `generated_assets`, `asset_paths`, `level_layout`, `game_ir`;
  every node now calls its agent with the Phase-3 single-input pydantic model;
  `logging` added; explicit error edges (`_failure_router` → `fail`/`rollback`,
  no cascading `None` into downstream agents); localization moved AFTER playtest
  and made fully non-blocking; retry path completes the Phase-4 asset round-trip
  (`preserve_assets` → recode → `restore_assets` → `clear_preserved`, closing
  Phase-4 adjacent bug #1). Stale `plan.modules` AttributeError (Phase-2 note)
  fixed via `_module_names(plan)` reading `required_modules`.
- Tests: `tests/test_orchestration_dryrun.py` (11 tests, fully offline — stub
  agents + fake workspace/art services, no GPU/Godot/LLM/network): state fields,
  happy-path traversal with per-agent single-model input assertions,
  quest/dialogue/level enablement, early-failure → fail without cascade,
  post-generation failure → rollback, localization non-blocking (exception and
  missing-keys), bounded retry with preserve/restore/clear ordering, graph-shape
  check that every production node has an edge to `fail`, source guard against
  legacy multi-positional calls.
- Makefile: new `test-orchestration` target (also wired into `verify-offline`
  and `help`).

**Adjacent bugs noticed (NOT fixed — other phases' scope):**
1. `backend/api/generation.py` (~lines 67-82) re-implements the Two-Attempt
   Rule for billing (`should_charge = success or attempt_number >= 2`) by
   reading `result["attempt_number"]` from the returned state — this duplicates
   orchestrator policy in the API layer. If the retry semantics change (e.g.
   MAX_ATTEMPTS, QA-only retries), credits silently diverge. Should be a single
   shared constant/policy owned by the orchestrator (billing phase).
2. Incremental updates: `skip_agents` from `IncrementalAnalyzer` is only
   honored for `art_director` in the orchestrator; quest/dialogue/level/coder/qa
   nodes ignore it, so "incremental" runs still regenerate everything except
   art. Full plumbing belongs to the incremental-update phase.
3. `GameDesignDocument.quest_complexity`/`dialogue_depth` default to `"none"`,
   so quest_designer/dialogue_writer are skipped unless the designer LLM
   explicitly sets them — fine, but the wizard flow never surfaces these knobs,
   meaning most generations will have zero quests/dialogues until the frontend
   wizard exposes them (frontend/integration phase).
4. `OrchestratorService.run_generation` returns the raw LangGraph state dict;
   callers like `api/generation.py` use `.get("attempt_number", 1)` defensively —
   there is no typed result model yet (API hardening phase).
5. The empty `backend/agents/playtest/` package directory remains alongside the
   real `backend/agents/playtester.py`; root-level legacy test scripts
   (`test_phase8_*.py`, `test_phase9_*.py`) are not collected by pytest config
   but still clutter the repo (cleanup phase).

## Phase 7 — Real status + health (this phase)

**What was built:** progress events are written to Redis (`generation:progress:{id}`,
TTL'd) on every orchestrator node transition and mirrored to Postgres at run end;
`GET /api/v1/generation/status/{id}` reads the real merged view (memory → Redis →
Postgres, plus live checkpoint when reachable, with wall-clock interpolation while
running) and returns 404 for unknown ids; `GET /api/v1/health` (new
`backend/api/health.py`, mounted in `main.py`) answers HTTP 200 with per-component
status and never crashes when infra is offline — matching the docker-compose
backend healthcheck (`curl -f http://localhost:8000/api/v1/health`). All mock/stub
bodies in `generation.py` are gone: `/download` really zips `godot_project/`
(404 unknown / 501 not-built), `/preview` refuses to fake a URL without an export,
DELETE really removes the workspace and clears durable progress. Tests:
`tests/test_generation_status_health.py` (16 tests, fully offline); Makefile target
`test-status-health` wired into `verify-offline`.

**Adjacent bugs noticed (NOT fixed — other phases' scope):**
1. Pre-existing test failure (verified on the clean tree before this phase):
   `tests/test_orchestration_persistence.py::test_ensure_checkpointer_falls_back_when_postgres_unreachable`
   asserts via `caplog` that a fallback warning is logged, but the log record is
   emitted before the caplog handler attaches its level (or under a logger name
   mismatch), so the assertion fails even though the behaviour is correct. The
   test should assert on the returned checkpointer type instead of log capture.
2. Carried over from Phase 5 note #1: `backend/api/generation.py` still
   re-implements the Two-Attempt billing rule (`should_charge = success or
   attempt_number >= 2`) in the API layer by reading raw state keys. Owned by
   the billing phase; left untouched here to avoid drive-by refactors.
3. `ProgressService._write_backend` prunes its in-memory store with operator
   precedence bug `-self._max_projects // 2` (negation applied before floor
   division), pruning zero entries when `_max_projects` is small. Harmless at
   the default 512 but worth fixing in the hardening phase.
4. `docker-compose.yml` nginx container still probes the legacy root `/health`
   while the backend service probes `/api/v1/health`; both endpoints exist, but
   the duplication belongs to the deployment-cleanup phase.

## Phase 9 — GameIR v2 + validator (this phase)

**What was built:**
- `backend/schemas/agent_schemas.py`: GameIR bumped to schema version 2
  (`GAME_IR_SCHEMA_VERSION = 2`). New fields, all backward-compatible via
  defaults: `schema_version`, `genre_template_id`, per-entity `EntityComponents`
  (movement/combat/interactable/quest_giver/sprite), `camera` (CameraConfig),
  `asset_manifest` (list of AssetManifestEntry), `localization_table`
  (LocalizationTable), `audio_map` (AudioMap/AudioMapZone), and an optional
  stable `id` on Room. v1-shaped dicts (no `schema_version`, no v2 fields)
  still parse cleanly; a *future* `schema_version` is rejected by the validator
  with `schema.version_unsupported`.
- `backend/services/ir_validator.py`: `validate_game_ir(ir, project_root=None,
  check_files=True)` returns a `ValidationReport` (never raises). Checks:
  referential integrity (entity→dialogue/sfx, quest_giver→quest, sprite→asset,
  dialogue npc→entity, choice.next→node, audio type mismatch), quest graph
  acyclicity (DFS cycle path reported) and reachability from root quests,
  spawn points and positioned entities inside room bounds, start/end room
  resolution, manifest `res://` path syntax plus on-disk existence under
  `project_root`, and tr() key presence in the localization table for dialogue
  text_keys, interact prompt_keys, quest titles and condition dicts. Errors are
  precise: `(code, dot-path, message)` triples, e.g.
  `quests.cycle @ quests.q3.requires[0] -> q5 -> q3`.
- `tests/test_ir_validator.py`: 39 offline tests — good v2 IR passes clean,
  v1 dict back-compat, and every error code above asserted individually with
  its dot-path. Makefile target `test-ir-validator` wired into
  `verify-offline`.

**Adjacent bugs noticed (NOT fixed — other phases' scope):**
1. `backend/services/godot_integrator.py` (`GodotIntegrator.integrate`) ignores
   every v2 field: entity components (movement/combat/interactable/
   quest_giver/sprite), `asset_manifest`, `localization_table`, `audio_map` and
   `camera` never influence generated scenes/scripts; only legacy
   `position_x/position_y` are read (lines ~342, ~361). The generator should
   consume the richer IR or the v2 additions will exist only on paper.
2. `_build_game_ir` in `backend/services/orchestration.py` (~line 936) emits
   entities without components or positions and never sets
   `genre_template_id` / the v2 collections, so orchestrator-produced IRs are
   effectively v1-shaped. The validator accepts them (backward-compat), but
   downstream fidelity suffers until the orchestration agents populate v2 data.
3. Items referenced by `QuestDef.items_required` cannot be cross-checked:
   there is no item registry in GameIR today, so the validator can only emit
   `refs.unmodelled_item` warnings. An `items` section belongs to a future IR
   revision.
4. Root-level legacy scripts `test_phase9_export.py` / `test_phase9_market*.py`
   predate this numbering scheme (they test export/marketplace, not the IR) and
   are not collected by pytest; renaming or folding them into `tests/` would
   avoid confusion about what "Phase 9" refers to.
