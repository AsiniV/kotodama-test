"""LLM-facing parameter schema for the Phase-10 Level Generator agent.

The ``LevelGeneratorAgent`` no longer lets the LLM imagine room coordinates:
the model only *chooses generation parameters* (this schema), and the real
geometry is produced deterministically by
:func:`backend.services.levelgen.generate_layout`.  Keeping the proposal
model in its own module avoids an import cycle between
``backend.schemas.agent_schemas`` and ``backend.services.levelgen``.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class LevelGenerationProposal(BaseModel):
    """A level-generation *request*, not a layout.

    Every field maps 1:1 onto a key understood by
    :func:`backend.services.levelgen.base.normalize_level_parameters`; the
    architect's ``level_parameters`` always win over anything the LLM
    proposes here (the agent merges plan params on top of this proposal).
    """

    algorithm: Literal["bsp", "cellular_automata", "wfc", "random_walk"] = "bsp"
    width: int = Field(default=64, ge=16, le=512)
    height: int = Field(default=64, ge=16, le=512)
    theme: str = "generic"
    min_rooms: int = Field(default=4, ge=2, le=32)
    max_rooms: int = Field(default=10, ge=2, le=64)
    corridor_width: int = Field(default=1, ge=1, le=5)
    enemy_density: float = Field(default=0.15, ge=0.0, le=1.0)
    item_density: float = Field(default=0.10, ge=0.0, le=1.0)
    poi_density: float = Field(default=0.2, ge=0.0, le=1.0)
    points_of_interest: List[str] = Field(default_factory=list)
    seed: Optional[int] = None
