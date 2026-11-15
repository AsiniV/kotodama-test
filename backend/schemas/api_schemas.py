"""
Pydantic schemas for API request/response validation.
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime
from enum import Enum


# ============== Enums ==============

class QuestComplexity(str, Enum):
    NONE = "none"
    SIMPLE = "simple"
    BRANCHING = "branching"
    EPIC = "epic"


class DialogueDepth(str, Enum):
    NONE = "none"
    LINEAR = "linear"
    BRANCHING = "branching"
    FULL_RPG = "full_rpg"


class ProjectStatus(str, Enum):
    DRAFT = "draft"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class GenerationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class AssetSlot(str, Enum):
    PLAYER = "player"
    ENEMY = "enemy"
    BACKGROUND = "background"
    UI_BUTTON = "ui_button"
    TILESET = "tileset"
    ITEM = "item"
    NPC = "npc"
    PROJECTILE = "projectile"
    HAZARD = "hazard"
    ICON = "icon"


class AssetType(str, Enum):
    SPRITE = "sprite"
    TEXTURE = "texture"
    SOUND = "sound"
    MUSIC = "music"
    UI = "ui"


# ============== Wizard Input Schemas ==============

# Single source of truth: WizardInput is defined in backend.schemas.agent_schemas
# and re-exported here so API code can keep importing it from this module.
# Canonical shape (Phase 2): controls: dict, text_description: str, plus
# quest_complexity / dialogue_depth. There must never be a second WizardInput class.
from backend.schemas.agent_schemas import WizardInput  # noqa: E402,F401 (re-export)


class RemixInput(BaseModel):
    """Input for remix/clone mode."""

    reference_game: str = Field(..., description="Reference game to clone/remix")
    modifications: str = Field(..., description="Desired modifications")
    project_name: str = Field(..., min_length=1, max_length=255)


# ============== Lore Schemas ==============

class LoreEntryCreate(BaseModel):
    """Create a new lore entry."""

    entry_type: str = Field(..., pattern="^(character|location|rule|item|faction|event)$")
    name: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    metadata: Optional[dict] = None


class LoreEntry(LoreEntryCreate):
    """Lore entry with ID."""

    id: int
    lore_collection_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LoreCollectionCreate(BaseModel):
    """Create a new lore collection."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    universe_name: Optional[str] = None


class LoreCollection(LoreCollectionCreate):
    """Lore collection with metadata."""

    id: int
    user_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    entries: list[LoreEntry] = []

    model_config = ConfigDict(from_attributes=True)


# ============== Project Schemas ==============

class ProjectCreate(BaseModel):
    """Create a new project."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class ProjectUpdate(BaseModel):
    """Update project metadata."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    status: Optional[ProjectStatus] = None


class Project(ProjectCreate):
    """Project with full metadata."""

    id: int
    user_id: int
    genre: Optional[str] = None
    perspective: Optional[str] = None
    art_style: Optional[str] = None
    setting: Optional[str] = None
    scale: Optional[str] = None
    controls: Optional[dict] = None
    has_saving: bool = False
    monetization: Optional[str] = None
    quest_complexity: QuestComplexity = QuestComplexity.NONE
    dialogue_depth: DialogueDepth = DialogueDepth.NONE
    lore_collection_id: Optional[int] = None
    status: ProjectStatus = ProjectStatus.DRAFT
    workspace_path: Optional[str] = None
    git_commit_hash: Optional[str] = None
    stability_score: Optional[float] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ============== Generation Schemas ==============

class GenerationRequest(BaseModel):
    """Request to start generation."""

    project_id: int
    request_type: str = Field(..., pattern="^(create|update|incremental)$")
    wizard_input: Optional[WizardInput] = None
    affected_modules: Optional[list[str]] = None


class GenerationHistory(BaseModel):
    """Generation history record."""

    id: int
    project_id: int
    attempt_number: int
    status: GenerationStatus
    request_type: str
    affected_modules: Optional[list[str]] = None
    error_message: Optional[str] = None
    stability_score: Optional[float] = None
    playtest_report: Optional[dict] = None
    credits_charged: int = 0
    started_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ============== Module Schemas ==============

class ModuleCreate(BaseModel):
    """Create a new module."""

    module_type: str
    module_name: str
    file_paths: list[str]
    signal_connections: Optional[list[dict]] = None
    dependencies: Optional[list[str]] = None
    is_core: bool = False


class Module(ModuleCreate):
    """Module with metadata."""

    id: int
    project_id: int
    version: str = "1.0.0"
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============== Asset Schemas ==============

class AssetMetadata(BaseModel):
    """Asset metadata schema as per spec."""

    path: str
    slot: AssetSlot
    asset_type: AssetType
    tags: list[str] = []
    dimensions: Optional[tuple[int, int]] = None
    duration_s: Optional[float] = None
    used_in: list[str] = []
    prompt_used: str
    provider: str = Field(..., pattern="^(local|fal|replicate)$")
    generated_at: datetime


class AssetCreate(AssetMetadata):
    """Create asset record."""

    project_id: int


class Asset(AssetCreate):
    """Asset with ID."""

    id: int

    model_config = ConfigDict(from_attributes=True)


# ============== Quest & Dialogue Schemas ==============

class QuestStage(BaseModel):
    """Quest stage definition."""

    id: str
    description: str
    type: str = Field(..., pattern="^(intro|objective|outro)$")
    requirements: Optional[list[str]] = None
    conditions: Optional[dict] = None
    location: Optional[str] = None
    rewards: Optional[list[dict]] = None


class QuestGraphCreate(BaseModel):
    """Create quest graph."""

    project_id: int
    quest_id: str
    title: str
    description: Optional[str] = None
    stages: list[QuestStage]
    dependencies: list[str] = []
    npcs_involved: list[str] = []
    items_required: list[str] = []
    rewards: Optional[list[dict]] = None


class QuestGraph(QuestGraphCreate):
    """Quest graph with validation status."""

    id: int
    validation_passed: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DialogueNode(BaseModel):
    """Dialogue tree node."""

    id: str
    speaker: str
    text_key: str
    choices: Optional[list[dict]] = None


class DialogueTreeCreate(BaseModel):
    """Create dialogue tree."""

    project_id: int
    dialogue_id: str
    npc_id: str
    trigger: Optional[str] = None
    nodes: list[DialogueNode]
    conditions: Optional[dict] = None


class DialogueTree(DialogueTreeCreate):
    """Dialogue tree with validation status."""

    id: int
    validation_passed: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============== Level Layout Schemas ==============

class LevelLayoutCreate(BaseModel):
    """Create level layout."""

    project_id: int
    algorithm: str = Field(..., pattern="^(bsp|cellular_automata|wfc|random_walk|poisson_disk)$")
    width: int = Field(..., ge=16, le=256)
    height: int = Field(..., ge=16, le=256)
    rooms: Optional[list[dict]] = None
    corridors: Optional[list[dict]] = None
    points_of_interest: list[str] = []
    enemy_spawn_points: Optional[list[dict]] = None
    item_spawn_points: Optional[list[dict]] = None
    start_room: str
    end_room: str


class LevelLayout(LevelLayoutCreate):
    """Level layout with validation status."""

    id: int
    validation_passed: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============== API Response Schemas ==============

class GenerationResponse(BaseModel):
    """Response from generation start endpoint."""
    
    success: bool
    project_id: str
    message: str
    estimated_time_seconds: int
    estimated_credits: int


class ProjectStatusResponse(BaseModel):
    """Current project status."""
    
    project_id: str
    status: str  # pending, running, completed, failed
    progress: int  # 0-100
    current_agent: Optional[str] = None
    logs: list[str] = []
    attempt_number: int = 1
    error_message: Optional[str] = None
    result: Optional[dict] = None


class APIResponse(BaseModel):
    """Generic API response wrapper."""

    success: bool
    message: str
    data: Optional[dict] = None


class CostEstimate(BaseModel):
    """Cost estimation for generation request."""

    credits_required: int
    estimated_time_seconds: int
    affected_modules: list[str]
    complexity_multiplier: float = 1.0
