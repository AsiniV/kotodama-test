"""
Pydantic schemas for agent inputs and outputs.
All data exchanged between agents uses these validated models.

Single source of truth: ``backend/schemas/api_schemas.py`` re-exports
``WizardInput`` (and friends) from this module.

Phase 2 schema contract (verified by tests/test_schema_contracts.py):
- ``GameDesignDocument`` carries ``quest_complexity`` / ``dialogue_depth``
  (read by the orchestrator's skip logic and by quest/dialogue agent prompts).
- ``WizardInput`` is defined exactly once, here; ``controls`` is a dict and the
  free-text field is named ``text_description`` everywhere.
- Bare lists are not valid LLM structured-output response models, so list
  outputs are wrapped in object models: ``QuestGraphList``, ``DialogueTreeList``
  (and ``PromptUpdates``). Agents pass these wrapper *classes* to
  ``BaseAgent._call_llm(prompt, response_model)`` — never ``type(list[...])``.

Phase 9 schema contract (verified by tests/test_ir_validator.py):
- ``GameIR`` is versioned (``schema_version``, GameIR v2) and carries entity
  components (``EntityComponents``), ``camera``, ``asset_manifest``,
  ``localization_table`` and ``audio_map`` — all with backward-compatible
  defaults so previously persisted v1 IR dicts still validate.
- Cross-referential consistency of a GameIR is checked by
  ``backend/services/ir_validator.py`` (not by pydantic), which reports precise
  machine-readable errors instead of raising on the first problem.
"""

from pydantic import BaseModel, ConfigDict, Field
from typing import Any, List, Literal, Optional
from datetime import datetime


# ============================================================================
# Game Designer Agent Schemas
# ============================================================================

class WizardInput(BaseModel):
    """Input from the 14-step wizard (single source of truth for API + agents).

    Canonical shape: ``controls`` is a mapping (action -> key/button) and the
    free-text description field is named ``text_description`` on every layer
    (frontend payload, API endpoint, orchestrator state, agents).
    """
    genre: str
    perspective: str
    art_style: str
    setting: str
    scale: str
    controls: dict[str, str] = Field(default_factory=dict)
    has_saving: bool = False
    monetization: str = "none"
    quest_complexity: Literal["none", "simple", "branching", "epic"] = "none"
    dialogue_depth: Literal["none", "linear", "branching", "full_rpg"] = "none"
    lore_collection_id: Optional[int] = None
    text_description: str
    project_name: str


class DesignerInput(BaseModel):
    """Single input model for the Game Designer agent."""
    wizard_input: WizardInput
    lore_context: Optional[str] = None


class GameDesignDocument(BaseModel):
    """Structured GDD output from Game Designer agent."""
    title: str
    genre: str
    perspective: str
    art_style: str
    setting: str
    scale: str
    core_mechanics: list[str]
    target_audience: str
    unique_selling_points: list[str]
    module_dependencies: list[str]  # Required modules
    estimated_modules: list[str]  # Modules to generate
    quest_complexity: Literal["none", "simple", "branching", "epic"] = "none"
    dialogue_depth: Literal["none", "linear", "branching", "full_rpg"] = "none"
    lore_context: Optional[str] = None


# ============================================================================
# Audio Pipeline Schemas (ЭТАП 2 — Sound Generation)
# ============================================================================

class AudioRequest(BaseModel):
    """Структурированный запрос на генерацию звука от Showrunner/Game IR.

    Добавь поле в корневую схему GameIR / GameDesignDocument:
        audio_requests: List[AudioRequest] = Field(default_factory=list)
    """
    id: str = Field(..., description="Уникальный ID, напр. 'bgm_main_theme' или 'sfx_footstep'")
    type: Literal["bgm", "sfx"]
    description: str = Field(..., description="Смысловое описание: 'тревожный синтвейв' или 'шаги по дереву'")
    duration_sec: int = Field(default=30, ge=5, le=120)
    loop: bool = Field(default=False, description="Зацикливать ли звук (для BGM)")


# ============================================================================
# Entity Components (GameIR v2 — Phase 9)
# ============================================================================


class MovementComponent(BaseModel):
    """How an entity moves. ``behavior`` is free-form ('static', 'patrol', ...)."""

    behavior: str = "static"
    speed: float = Field(default=0.0, ge=0.0)
    patrol_radius: float = Field(default=0.0, ge=0.0)


class CombatComponent(BaseModel):
    """Damage model for hostile entities."""

    damage: int = Field(default=1, ge=0)
    attack_range: float = Field(default=32.0, ge=0.0)
    attack_cooldown_s: float = Field(default=1.0, gt=0.0)


class InteractableComponent(BaseModel):
    """Player-triggered interaction; ``dialogue_id`` must reference a DialogueTree."""

    trigger: Literal["interact", "proximity", "pickup"] = "interact"
    prompt_key: Optional[str] = Field(
        default=None, description="Localization key shown as the interaction prompt"
    )
    dialogue_id: Optional[str] = Field(
        default=None, description="ID of the DialogueTree opened by this interaction"
    )


class QuestGiverComponent(BaseModel):
    """Quests offered by this entity; IDs must reference QuestGraph.quest_id."""

    quest_ids: List[str] = Field(default_factory=list)


class SpriteComponent(BaseModel):
    """Visual representation; ``asset_id`` references AssetManifestEntry.id when set."""

    asset_id: Optional[str] = Field(
        default=None, description="Asset manifest entry id (res:// sprite asset)"
    )
    flip_h: bool = False
    z_index: int = 0


class EntityComponents(BaseModel):
    """Optional ECS-style component bundle attached to an EntityRequest (Phase 9)."""

    movement: Optional[MovementComponent] = None
    combat: Optional[CombatComponent] = None
    interactable: Optional[InteractableComponent] = None
    quest_giver: Optional[QuestGiverComponent] = None
    sprite: Optional[SpriteComponent] = None


class EntityRequest(BaseModel):
    """Сущность игрового мира (NPC, объект, враг) для Godot-интегратора.

    Интегратор превращает каждую сущность в узел Sprite2D внутри main_level.tscn,
    подставляя спрайт res://assets/sprites/<id>.png (если он существует) и
    генерируя per-entity .gd скрипт со специфичной логикой.
    """
    id: str = Field(..., description="Уникальный ID, напр. 'npc_blacksmith'")
    name: Optional[str] = Field(default=None, description="Отображаемое имя")
    type: Literal["player", "npc", "enemy", "item", "hazard", "decoration"] = "npc"
    description: str = Field(default="", description="Смысловое описание сущности")
    sprite: Optional[str] = Field(default=None, description="Имя спрайта без расширения (по умолчанию = id)")
    position_x: Optional[float] = Field(default=None, description="X-координата на уровне")
    position_y: Optional[float] = Field(default=None, description="Y-координата на уровне")
    dialogue_id: Optional[str] = Field(default=None, description="ID диалогового дерева, привязанного к сущности")
    sfx_ids: List[str] = Field(
        default_factory=list,
        description="ID звуковых эффектов из AudioRequest (type='sfx'), которые издаёт эта сущность",
    )
    components: EntityComponents = Field(
        default_factory=EntityComponents,
        description="Компоненты сущности (movement/combat/interactable/quest_giver/sprite) — GameIR v2",
    )


# ============================================================================
# Architect Agent Schemas
# ============================================================================

class ArchitecturePlan(BaseModel):
    """Scene structure and signal contract plan."""
    scene_tree: dict  # Hierarchical scene structure
    required_modules: list[dict]  # Module specifications
    signal_contracts: list[dict]  # Signal definitions with module_ prefix
    asset_slots_needed: list[str]  # Which of the 10 slots are needed
    level_parameters: Optional[dict] = None  # For procedural generation
    save_system_required: bool = False


class ArchitectInput(BaseModel):
    """Single input model for the Architect agent."""
    design_document: GameDesignDocument


# ============================================================================
# Quest Designer Agent Schemas
# ============================================================================

class QuestStage(BaseModel):
    """Individual stage in a quest state machine."""
    id: str
    description: str
    type: Literal["intro", "objective", "outro"]
    requirements: Optional[list[str]] = None  # Items/flags needed
    conditions: Optional[dict] = None  # Conditions to complete
    location: Optional[str] = None
    rewards: Optional[list[dict]] = None


class QuestGraph(BaseModel):
    """Complete quest state machine graph."""
    quest_id: str
    title: str
    description: str
    stages: list[QuestStage]
    dependencies: list[str]  # Other quest IDs this depends on
    npcs_involved: list[str]
    items_required: list[str]


class QuestGraphList(BaseModel):
    """Wrapper model for the Quest Designer's list output.

    Used as the ``response_model`` passed to ``BaseAgent._call_llm`` /
    ``LLMClient.generate`` (structured-output schemas must be JSON objects,
    never bare arrays). The orchestrator reads ``.quests`` off this model.
    """
    quests: list[QuestGraph] = Field(default_factory=list)


class QuestDesignerInput(BaseModel):
    """Single input model for the Quest Designer agent."""
    design_document: GameDesignDocument
    architecture_plan: Optional[ArchitecturePlan] = None
    lore_context: Optional[str] = None
    item_registry: list[str] = Field(default_factory=list)
    npc_registry: list[str] = Field(default_factory=list)
    location_registry: list[str] = Field(default_factory=list)


# ============================================================================
# Dialogue Writer Agent Schemas
# ============================================================================

class DialogueChoice(BaseModel):
    """Player choice in a dialogue node."""
    text_key: str
    next: str
    requires: Optional[str] = None  # Condition to show this choice
    action: Optional[str] = None  # Action triggered (give_item, set_flag, etc.)


class DialogueNode(BaseModel):
    """Node in a branching dialogue tree."""
    id: str
    speaker: str
    text_key: str
    choices: list[DialogueChoice]


class DialogueTree(BaseModel):
    """Complete branching dialogue tree."""
    dialogue_id: str
    npc_id: str
    trigger: str  # What triggers this dialogue
    nodes: list[DialogueNode]
    conditions: dict  # Actions and their effects


class DialogueTreeList(BaseModel):
    """Wrapper model for the Dialogue Writer's list output.

    Used as the ``response_model`` passed to ``BaseAgent._call_llm`` /
    ``LLMClient.generate`` (structured-output schemas must be JSON objects,
    never bare arrays). The orchestrator reads ``.dialogues`` off this model.
    """
    dialogues: list[DialogueTree] = Field(default_factory=list)


class DialogueWriterInput(BaseModel):
    """Single input model for the Dialogue Writer agent."""
    design_document: GameDesignDocument
    quest_graphs: list[QuestGraph] = Field(default_factory=list)
    lore_context: Optional[str] = None
    localization_keys: list[str] = Field(default_factory=list)
    item_registry: list[str] = Field(default_factory=list)
    flag_registry: list[str] = Field(default_factory=list)
    quest_registry: list[str] = Field(default_factory=list)


# ============================================================================
# Art Director Agent Schemas
# ============================================================================

class AssetPrompt(BaseModel):
    """Prompt for generating a single asset."""
    slot: Literal["player", "enemy", "background", "ui_button", "tileset", "item", "npc", "projectile", "hazard", "icon"]
    prompt: str
    negative_prompt: str = ""
    width: int = 512
    height: int = 512
    style: str


class GeneratedAsset(BaseModel):
    """Metadata for a generated asset."""
    path: str
    slot: Literal["player", "enemy", "background", "ui_button", "tileset", "item", "npc", "projectile", "hazard", "icon"]
    asset_type: Literal["sprite", "texture", "sound", "music", "ui"]
    tags: list[str]
    dimensions: Optional[tuple[int, int]] = None
    duration_s: Optional[float] = None
    used_in: list[str]
    prompt_used: str
    provider: Literal["local", "fal", "replicate"]
    generated_at: datetime


class AssetPromptsOutput(BaseModel):
    """Output from Art Director agent."""
    prompts: list[AssetPrompt]
    assets: list[GeneratedAsset]


class ArtDirectorInput(BaseModel):
    """Single input model for the Art Director agent."""
    architecture_plan: ArchitecturePlan
    lore_context: Optional[str] = None
    art_style: str = "pixel-art"


# ============================================================================
# Prompt Refiner Agent Schemas
# ============================================================================

class GenerationRecord(BaseModel):
    """One generation attempt record used by the Prompt Refiner meta-agent."""
    agent: str = "unknown"
    success: bool = False
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)


class PromptUpdate(BaseModel):
    """Updated system prompt for a single agent."""
    agent_name: str
    updated_prompt: str


class PromptUpdates(BaseModel):
    """Wrapper model for the Prompt Refiner's list output.

    Used as the ``response_model`` passed to ``BaseAgent._call_llm`` /
    ``LLMClient.generate`` (structured-output schemas must be JSON objects,
    never bare arrays).
    """
    updates: list[PromptUpdate] = Field(default_factory=list)


class PromptRefinerInput(BaseModel):
    """Single input model for the Prompt Refiner agent."""
    generation_history: list[GenerationRecord] = Field(default_factory=list)


# ============================================================================
# Coder Agent Schemas
# ============================================================================

class GeneratedFile(BaseModel):
    """A single generated file."""
    path: str
    content: str
    file_type: Literal["gdscript", "tscn", "json", "import"]
    module_id: Optional[str] = None


class CoderInput(BaseModel):
    """Input for the Coder agent."""
    architecture_plan: ArchitecturePlan
    quest_graphs: Optional[list[QuestGraph]] = None
    dialogue_trees: Optional[list[DialogueTree]] = None
    asset_paths: Optional[list[str]] = None
    level_layout: Optional[dict] = None


class CoderOutput(BaseModel):
    """Output from Coder agent."""
    files: list[GeneratedFile]
    modules_created: list[str]
    signals_registered: list[str]


# ============================================================================
# QA Agent Schemas
# ============================================================================

class QAError(BaseModel):
    """Single error found by QA."""
    file_path: str
    error_type: Literal["syntax", "signal_contract", "asset_reference", "guard_violation"]
    message: str
    line_number: Optional[int] = None


class QAReport(BaseModel):
    """Quality assurance report."""
    passed: bool
    errors: list[QAError]
    warnings: list[str]
    files_checked: int
    signals_verified: int


class QAInput(BaseModel):
    """Single input model for the QA agent (deterministic code validation)."""
    coder_output: CoderOutput
    asset_paths: list[str] = Field(default_factory=list)
    signal_contracts: list[dict] = Field(default_factory=list)


# ============================================================================
# Playtest Agent Schemas
# ============================================================================

class PlaytestMetrics(BaseModel):
    """Metrics collected during playtest."""
    fps_avg: float
    fps_min: float
    engine_errors: int
    module_errors: int
    crashed: bool = False
    timed_out: bool = False
    reached_end_point: bool = False
    items_collected: int = 0
    npcs_interacted: int = 0
    quests_started: int = 0
    quests_completed: int = 0
    dialogues_opened: int = 0
    player_deaths: int = 0
    stuck_frames: int = 0


class PlaytestReport(BaseModel):
    """Playtest results."""
    success: bool = False
    stability_score: float  # 0-100
    fps_avg: float = 0.0
    fps_min: float = 0.0
    engine_errors: int = 0
    module_errors: int = 0
    crashed: bool = False
    timed_out: bool = False
    has_start_point: bool = False
    has_end_point: bool = False
    has_line_of_sight: bool = False
    frames_rendered: int = 0
    log_output: str = ""
    error_message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class PlaytestConfig(BaseModel):
    """Configuration for playtest run."""
    workspace_path: str
    max_frames: int = 900
    timeout_seconds: int = 60


# ============================================================================
# Level Generator Schemas
# ============================================================================

class Room(BaseModel):
    """Room in a procedurally generated level."""
    x: int
    y: int
    width: int
    height: int
    room_type: str
    id: Optional[str] = Field(
        default=None,
        description="Стабильный идентификатор комнаты ('room_0'); "
        "если отсутствует — вычисляется как 'room_{index}' (GameIR v2, Phase 9)",
    )


class Corridor(BaseModel):
    """Corridor connecting rooms."""
    start: tuple[int, int]
    end: tuple[int, int]
    width: int


class LevelLayout(BaseModel):
    """Procedurally generated level layout."""
    algorithm: str
    width: int
    height: int
    rooms: list[Room]
    corridors: list[Corridor]
    points_of_interest: list[dict]
    enemy_spawn_points: list[tuple[int, int]]
    item_spawn_points: list[tuple[int, int]]
    start_room: str
    end_room: str
    validation_passed: bool = False


class LevelGeneratorInput(BaseModel):
    """Single input model for the Level Generator agent."""
    architecture_plan: ArchitecturePlan
    max_enemy_density: float = 0.5
    max_item_density: float = 0.5


# ============================================================================
# Localization Schemas
# ============================================================================

class LocalizationEntry(BaseModel):
    """Single localization string."""
    key: str
    value: str
    category: str  # quest, dialogue, item, ui, npc


class LocalizationFile(BaseModel):
    """Complete localization file."""
    locale: str
    strings: dict[str, str]  # key -> value mapping


class LocalizationOutput(BaseModel):
    """Output from Localization Manager."""
    entries: list[LocalizationEntry]
    localization_files: list[LocalizationFile]
    missing_keys: list[str]  # tr() calls without keys


class LocalizationInput(BaseModel):
    """Single input model for the Localization Manager agent."""
    dialogue_trees: list[DialogueTree] = Field(default_factory=list)
    quest_graphs: list[QuestGraph] = Field(default_factory=list)
    generated_file_paths: list[str] = Field(default_factory=list)


# ============================================================================
# Game IR — корневая схема (объявлена после всех зависимых схем)
# ============================================================================

#: Текущая версия схемы GameIR (GameIR v2 — Phase 9).
GAME_IR_SCHEMA_VERSION = 2


class CameraConfig(BaseModel):
    """Камера игрока; значения совпадают с настройками godot_core camera controller."""

    mode: Literal["top_down", "platformer", "first_person"] = "top_down"
    follow_smoothing: float = Field(default=0.1, ge=0.0, le=1.0)
    zoom: float = Field(default=1.0, gt=0.0)
    deadzone_px: int = Field(default=48, ge=0)


class AssetManifestEntry(BaseModel):
    """Одна запись манифеста ассетов. ``path`` — res://-путь внутри Godot-проекта."""

    id: str = Field(..., description="Уникальный ID ассета")
    path: str = Field(..., description="res:// путь к файлу внутри проекта")
    kind: Literal["sprite", "audio", "music", "tileset", "ui", "font", "other"] = "sprite"
    entity_id: Optional[str] = Field(
        default=None, description="Ссылка на EntityRequest.id (для спрайтов сущностей)"
    )
    audio_request_id: Optional[str] = Field(
        default=None, description="Ссылка на AudioRequest.id (для аудио-ассетов)"
    )


class LocalizationTable(BaseModel):
    """Локализационная таблица: locale -> (ключ -> строка). Ключи используются в tr()."""

    default_locale: str = "en"
    entries: dict[str, dict[str, str]] = Field(default_factory=dict)

    def keys_for(self, locale: str) -> set[str]:
        """Return the set of tr() keys defined for *locale* (empty if unknown)."""
        return set(self.entries.get(locale, {}))


class AudioMapZone(BaseModel):
    """Звуковая зона уровня: привязка BGM/SFX к прямоугольной области."""

    id: str
    rect: tuple[float, float, float, float] = Field(
        ..., description="(x, y, width, height) в пикселях уровня"
    )
    bgm_id: Optional[str] = Field(default=None, description="AudioRequest.id (type='bgm')")
    sfx_ids: List[str] = Field(default_factory=list)


class AudioMap(BaseModel):
    """Карта звука уровня: зоны + глобальные эмбиент-слои."""

    zones: List[AudioMapZone] = Field(default_factory=list)
    ambient: List[str] = Field(
        default_factory=list, description="ID фоновых слоёв из AudioRequest (bgm или sfx)"
    )


class GameIR(BaseModel):
    """Game Intermediate Representation — корневая схема игры для пайплайна.

    Агрегирует GDD, структурированные запросы на аудио, сущности мира,
    квесты и диалоги — всё, что нужно Godot-интегратору для сборки проекта.

    GameIR v2 (Phase 9) добавляет ``schema_version``, ``genre_template_id``,
    компоненты сущностей (:class:`EntityComponents`), ``camera``,
    ``asset_manifest``, ``localization_table`` и ``audio_map`` — все новые поля
    имеют безопасные значения по умолчанию, поэтому сериализованные IR версии 1
    загружаются без изменений (backward compatibility).
    """
    schema_version: int = GAME_IR_SCHEMA_VERSION
    genre_template_id: Optional[str] = None
    design_document: Optional[GameDesignDocument] = None
    audio_requests: List[AudioRequest] = Field(default_factory=list)
    entities: List[EntityRequest] = Field(default_factory=list)
    quests: List[QuestGraph] = Field(default_factory=list)
    dialogues: List[DialogueTree] = Field(default_factory=list)
    level_layout: Optional[LevelLayout] = None
    camera: CameraConfig = Field(default_factory=CameraConfig)
    asset_manifest: List[AssetManifestEntry] = Field(default_factory=list)
    localization_table: LocalizationTable = Field(default_factory=LocalizationTable)
    audio_map: AudioMap = Field(default_factory=AudioMap)


# ============================================================================
# Orchestration Schemas
# ============================================================================

class GenerationRequest(BaseModel):
    """Complete generation request."""
    request_type: Literal["create", "update", "incremental"]
    wizard_input: Optional[WizardInput] = None
    project_id: Optional[int] = None
    affected_modules: Optional[list[str]] = None


class GenerationResult(BaseModel):
    """Result of a generation attempt."""
    success: bool
    attempt_number: int
    credits_charged: int
    stability_score: Optional[float] = None
    error_message: Optional[str] = None
    files_generated: int = 0
    modules_created: list[str] = []
