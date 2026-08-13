"""
SQLAlchemy models for Kotodama database.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Float, ForeignKey, JSON, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.db.session import Base


class User(Base):
    """User account model."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    projects = relationship("Project", back_populates="user", cascade="all, delete-orphan")
    lore_collections = relationship("LoreCollection", back_populates="user", cascade="all, delete-orphan")
    subscriptions = relationship("Subscription", back_populates="user", cascade="all, delete-orphan")


class Project(Base):
    """Generated game project model."""

    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    genre = Column(String(100))
    perspective = Column(String(50))
    art_style = Column(String(100))
    setting = Column(String(255))
    scale = Column(String(50))
    controls = Column(JSON)
    has_saving = Column(Boolean, default=False)
    monetization = Column(String(50))
    quest_complexity = Column(String(50), default="none")
    dialogue_depth = Column(String(50), default="none")
    lore_collection_id = Column(Integer, ForeignKey("lore_collections.id"))
    status = Column(String(50), default="draft")  # draft, generating, ready, failed
    workspace_path = Column(String(500))
    git_commit_hash = Column(String(64))
    stability_score = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="projects")
    lore_collection = relationship("LoreCollection")
    generations = relationship("GenerationHistory", back_populates="project", cascade="all, delete-orphan")
    modules = relationship("Module", back_populates="project", cascade="all, delete-orphan")


class LoreCollection(Base):
    """User's knowledge base for RAG (characters, world rules, etc.)."""

    __tablename__ = "lore_collections"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    universe_name = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="lore_collections")
    entries = relationship("LoreEntry", back_populates="lore_collection", cascade="all, delete-orphan")


class LoreEntry(Base):
    """Individual lore entry (character, location, rule, etc.)."""

    __tablename__ = "lore_entries"

    id = Column(Integer, primary_key=True, index=True)
    lore_collection_id = Column(Integer, ForeignKey("lore_collections.id"), nullable=False)
    entry_type = Column(String(50), nullable=False)  # character, location, rule, item, faction, event
    name = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    metadata = Column(JSON)
    embedding = Column(JSON)  # PGVector embedding stored as JSON for compatibility
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    lore_collection = relationship("LoreCollection", back_populates="entries")

    __table_args__ = (
        Index("idx_lore_entry_type", "entry_type"),
        Index("idx_lore_entry_name", "name"),
    )


class Subscription(Base):
    """User subscription plan."""

    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    plan_type = Column(String(50), nullable=False)  # free, starter, pro, studio
    credits_remaining = Column(Integer, default=0)
    credits_total = Column(Integer, default=0)
    stripe_subscription_id = Column(String(255), unique=True)
    current_period_start = Column(DateTime(timezone=True))
    current_period_end = Column(DateTime(timezone=True))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="subscriptions")


class GenerationHistory(Base):
    """History of generation attempts for a project."""

    __tablename__ = "generation_history"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    attempt_number = Column(Integer, nullable=False)
    status = Column(String(50), nullable=False)  # pending, running, success, failed, rolled_back
    request_type = Column(String(50), nullable=False)  # create, update, incremental
    affected_modules = Column(JSON)
    error_message = Column(Text)
    stability_score = Column(Float)
    playtest_report = Column(JSON)
    credits_charged = Column(Integer, default=0)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))

    # Relationships
    project = relationship("Project", back_populates="generations")


class Module(Base):
    """Generated module/plugin for a project."""

    __tablename__ = "modules"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    module_type = Column(String(100), nullable=False)  # PlayerController, InventorySystem, etc.
    module_name = Column(String(255), nullable=False)
    file_paths = Column(JSON)  # List of generated file paths
    signal_connections = Column(JSON)
    dependencies = Column(JSON)
    is_core = Column(Boolean, default=False)
    version = Column(String(20), default="1.0.0")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    project = relationship("Project", back_populates="modules")


class Asset(Base):
    """Generated asset metadata."""

    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    path = Column(String(500), nullable=False)
    slot = Column(String(50), nullable=False)  # player, enemy, background, etc.
    asset_type = Column(String(50), nullable=False)  # sprite, texture, sound, music, ui
    tags = Column(JSON)
    dimensions = Column(JSON)  # [width, height] for images
    duration_s = Column(Float)  # for audio
    used_in = Column(JSON)  # module IDs
    prompt_used = Column(Text)
    provider = Column(String(50))  # local, fal, replicate
    generated_at = Column(DateTime(timezone=True), server_default=func.now())


class QuestGraph(Base):
    """Generated quest state machine graph."""

    __tablename__ = "quest_graphs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    quest_id = Column(String(100), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    stages = Column(JSON, nullable=False)
    dependencies = Column(JSON)
    npcs_involved = Column(JSON)
    items_required = Column(JSON)
    rewards = Column(JSON)
    validation_passed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DialogueTree(Base):
    """Generated branching dialogue tree."""

    __tablename__ = "dialogue_trees"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    dialogue_id = Column(String(100), nullable=False)
    npc_id = Column(String(100), nullable=False)
    trigger = Column(String(255))
    nodes = Column(JSON, nullable=False)
    conditions = Column(JSON)
    validation_passed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class LevelLayout(Base):
    """Procedurally generated level layout."""

    __tablename__ = "level_layouts"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    algorithm = Column(String(50), nullable=False)  # bsp, cellular_automata, wfc, random_walk
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    rooms = Column(JSON)
    corridors = Column(JSON)
    points_of_interest = Column(JSON)
    enemy_spawn_points = Column(JSON)
    item_spawn_points = Column(JSON)
    start_room = Column(String(100))
    end_room = Column(String(100))
    validation_passed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
