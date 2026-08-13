"""
Incremental Update Analyzer - Determines which modules are affected by changes.

Features:
- Compare old vs new GDD
- Identify affected modules
- Route only necessary agents
- Support two-attempt rule with credit logic
"""

from typing import Optional
from pydantic import BaseModel, Field


class ChangeImpact(BaseModel):
    """Represents the impact of a change."""
    module_id: str
    change_type: str  # "create", "modify", "delete"
    severity: str = Field(..., description="low|medium|high")
    requires_coder: bool = True
    requires_qa: bool = True
    requires_playtest: bool = True
    assets_affected: bool = False
    quests_affected: bool = False
    dialogues_affected: bool = False


class IncrementalUpdatePlan(BaseModel):
    """Plan for incremental update."""
    affected_modules: list[ChangeImpact] = []
    total_changes: int = 0
    high_severity_count: int = 0
    estimated_credits: float = 0.0
    requires_full_regeneration: bool = False
    skip_agents: list[str] = []  # Agents to skip in pipeline


class IncrementalAnalyzer:
    """Analyzes changes and creates incremental update plans."""

    def __init__(self):
        self.module_dependencies = {
            "player_controller": ["input_system", "physics"],
            "enemy_ai": ["pathfinding", "combat"],
            "inventory": ["item_database", "ui"],
            "quest_manager": ["dialogue_system", "world_state"],
            "dialogue_system": ["localization", "world_state"],
            "save_system": ["all"],  # Depends on everything
        }

    def analyze(self, old_gdd: dict, new_gdd: dict) -> IncrementalUpdatePlan:
        """Compare GDDs and determine affected modules."""
        plan = IncrementalUpdatePlan()
        
        # Check for major structural changes
        if self._is_major_change(old_gdd, new_gdd):
            plan.requires_full_regeneration = True
            return plan
        
        # Compare modules
        old_modules = set(old_gdd.get("modules", []))
        new_modules = set(new_gdd.get("modules", []))
        
        # New modules
        for module_id in new_modules - old_modules:
            plan.affected_modules.append(ChangeImpact(
                module_id=module_id,
                change_type="create",
                severity="medium",
            ))
        
        # Removed modules
        for module_id in old_modules - new_modules:
            plan.affected_modules.append(ChangeImpact(
                module_id=module_id,
                change_type="delete",
                severity="low",
                requires_coder=False,
                requires_qa=True,
                requires_playtest=True,
            ))
        
        # Modified modules - compare configurations
        common_modules = old_modules & new_modules
        for module_id in common_modules:
            old_config = self._get_module_config(old_gdd, module_id)
            new_config = self._get_module_config(new_gdd, module_id)
            
            if old_config != new_config:
                severity = self._calculate_severity(old_config, new_config)
                change_impact = ChangeImpact(
                    module_id=module_id,
                    change_type="modify",
                    severity=severity,
                )
                
                # Check if quests/dialogues/assets affected
                if "quest" in module_id.lower():
                    change_impact.quests_affected = True
                    plan.skip_agents = [a for a in plan.skip_agents if a != "quest_designer"]
                
                if "dialogue" in module_id.lower():
                    change_impact.dialogues_affected = True
                    plan.skip_agents = [a for a in plan.skip_agents if a != "dialogue_writer"]
                
                if any(x in module_id.lower() for x in ["art", "sprite", "texture"]):
                    change_impact.assets_affected = True
                
                plan.affected_modules.append(change_impact)
        
        # Calculate totals
        plan.total_changes = len(plan.affected_modules)
        plan.high_severity_count = sum(
            1 for m in plan.affected_modules if m.severity == "high"
        )
        
        # Estimate credits
        plan.estimated_credits = self._estimate_credits(plan.affected_modules)
        
        # Determine agents to skip
        if not any(m.quests_affected for m in plan.affected_modules):
            plan.skip_agents.append("quest_designer")
        
        if not any(m.dialogues_affected for m in plan.affected_modules):
            plan.skip_agents.append("dialogue_writer")
        
        if not any(m.assets_affected for m in plan.affected_modules):
            plan.skip_agents.append("art_director")
        
        return plan

    def _is_major_change(self, old_gdd: dict, new_gdd: dict) -> bool:
        """Check if change requires full regeneration."""
        # Genre change
        if old_gdd.get("genre") != new_gdd.get("genre"):
            return True
        
        # Perspective change
        if old_gdd.get("perspective") != new_gdd.get("perspective"):
            return True
        
        # Scale change (2D ↔ 3D)
        old_scale = old_gdd.get("scale", "2D")
        new_scale = new_gdd.get("scale", "2D")
        if old_scale != new_scale:
            return True
        
        # More than 50% modules changed
        old_modules = set(old_gdd.get("modules", []))
        new_modules = set(new_gdd.get("modules", []))
        if len(old_modules.symmetric_difference(new_modules)) > max(len(old_modules), len(new_modules)) * 0.5:
            return True
        
        return False

    def _get_module_config(self, gdd: dict, module_id: str) -> dict:
        """Extract module configuration from GDD."""
        modules = gdd.get("module_configs", {})
        return modules.get(module_id, {})

    def _calculate_severity(self, old_config: dict, new_config: dict) -> str:
        """Calculate change severity."""
        changed_keys = set(old_config.keys()) ^ set(new_config.keys())
        
        critical_keys = {"core_mechanic", "controls", "win_condition"}
        important_keys = {"parameters", "dependencies", "signals"}
        
        if any(k in critical_keys for k in changed_keys):
            return "high"
        elif any(k in important_keys for k in changed_keys):
            return "medium"
        else:
            return "low"

    def _estimate_credits(self, impacts: list[ChangeImpact]) -> float:
        """Estimate credits required for changes."""
        base_cost = 0.5  # Base cost per generation
        
        severity_multipliers = {
            "low": 0.5,
            "medium": 1.0,
            "high": 2.0,
        }
        
        total = 0.0
        for impact in impacts:
            if impact.requires_coder:
                multiplier = severity_multipliers.get(impact.severity, 1.0)
                total += base_cost * multiplier
                
                # Additional costs
                if impact.quests_affected:
                    total += 0.3
                if impact.dialogues_affected:
                    total += 0.3
                if impact.assets_affected:
                    total += 0.4
        
        return round(total, 2)


# Singleton instance
_analyzer: Optional[IncrementalAnalyzer] = None


def get_incremental_analyzer() -> IncrementalAnalyzer:
    """Get or create analyzer singleton."""
    global _analyzer
    if _analyzer is None:
        _analyzer = IncrementalAnalyzer()
    return _analyzer
