"""
Pydantic schemas for agent inputs and outputs.
All data exchanged between agents uses these validated models.
"""

from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from datetime import datetime


# ============================================================================
# Game Designer Agent Schemas
# ============================================================================

class WizardInput(BaseModel):
    """Input from the 14-step wizard."""
    genre: str
    perspective: str
    art_style: str
    setting: str
    scale: str
    controls: dict
    has_saving: bool = False
    monetization: str
    quest_complexity: Literal["none", "simple", "branching", "epic"] = "none"
    dialogue_depth: Literal["none", "linear", "branching", "full_rpg"] = "none"
    lore_collection_id: Optional[int] = None
    text_description: str
    project_name: str


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


# ============================================================================
# Game IR — корневая схема (объявлена после всех зависимых схем)
# ============================================================================

class GameIR(BaseModel):
    """Game Intermediate Representation — корневая схема игры для пайплайна.

    Агрегирует GDD, структурированные запросы на аудио, сущности мира,
    квесты и диалоги — всё, что нужно Godot-интегратору для сборки проекта.
    """
    design_document: Optional[GameDesignDocument] = None
    audio_requests: List[AudioRequest] = Field(default_factory=list)
    entities: List[EntityRequest] = Field(default_factory=list)
    quests: List[QuestGraph] = Field(default_factory=list)
    dialogues: List[DialogueTree] = Field(default_factory=list)
    level_layout: Optional[LevelLayout] = None


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
