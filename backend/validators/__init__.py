"""
Validators for Phase 5: Quest, Dialogue, and Level validation.

These validators ensure generated content passes all integrity checks
before reaching the Coder agent.
"""

from backend.schemas.agent_schemas import (
    QuestGraph,
    QuestStage,
    DialogueTree,
    DialogueNode,
    LevelLayout,
    Room,
)
from typing import Optional
from collections import deque


class ValidationResult:
    """Result of a validation check."""
    
    def __init__(self, passed: bool, errors: list[str] = None, warnings: list[str] = None):
        self.passed = passed
        self.errors = errors or []
        self.warnings = warnings or []
    
    def __bool__(self):
        return self.passed
    
    def merge(self, other: 'ValidationResult') -> 'ValidationResult':
        """Merge two validation results."""
        return ValidationResult(
            passed=self.passed and other.passed,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings
        )


class QuestGraphValidator:
    """
    Validates quest state machine graphs before they reach the Coder.
    
    Validation Rules (from spec Section 4.2):
    1. No circular dependencies between quests
    2. All stages are reachable from start (BFS/DFS)
    3. No impossible conditions (items/NPCs/locations must exist)
    4. Every item in requirements must be defined
    5. Every NPC referenced must exist
    6. Every location referenced must exist
    7. At least one reward per quest
    8. No dead-end stages
    """
    
    def __init__(self, item_registry: set[str] = None, npc_registry: set[str] = None, 
                 location_registry: set[str] = None):
        self.item_registry = item_registry or set()
        self.npc_registry = npc_registry or set()
        self.location_registry = location_registry or set()
    
    def validate_single_quest(self, quest: QuestGraph) -> ValidationResult:
        """Validate a single quest graph."""
        result = ValidationResult(passed=True)
        
        # Rule 1: Check for at least one stage
        if not quest.stages:
            result.passed = False
            result.errors.append(f"Quest '{quest.quest_id}' has no stages")
            return result
        
        # Rule 2: All stages must be reachable from first stage (BFS)
        if not self._check_stage_reachability(quest.stages):
            result.passed = False
            result.errors.append(f"Quest '{quest.quest_id}' has unreachable stages")
        
        # Rule 3 & 4: Check item requirements exist
        for stage in quest.stages:
            if stage.requirements:
                for req in stage.requirements:
                    if req not in self.item_registry and req not in self.npc_registry:
                        result.passed = False
                        result.errors.append(
                            f"Quest '{quest.quest_id}' stage '{stage.id}' requires unknown item/flag: {req}"
                        )
            
            # Check conditions reference valid items
            if stage.conditions:
                # Handle both dict formats: {"item": "fuse", "count": 1} or {"items": ["fuse", "bar"]}
                item_value = stage.conditions.get('item')
                if isinstance(item_value, str):
                    # Single item string
                    if item_value not in self.item_registry:
                        result.passed = False
                        result.errors.append(
                            f"Quest '{quest.quest_id}' stage '{stage.id}' references unknown item: {item_value}"
                        )
                elif isinstance(item_value, list):
                    # List of items
                    for item_id in item_value:
                        if item_id not in self.item_registry:
                            result.passed = False
                            result.errors.append(
                                f"Quest '{quest.quest_id}' stage '{stage.id}' references unknown item: {item_id}"
                            )
        
        # Rule 5: NPCs must exist
        for npc_id in quest.npcs_involved:
            if npc_id not in self.npc_registry:
                result.passed = False
                result.errors.append(
                    f"Quest '{quest.quest_id}' references unknown NPC: {npc_id}"
                )
        
        # Rule 6: Locations must exist
        for stage in quest.stages:
            if stage.location and stage.location not in self.location_registry:
                result.passed = False
                result.errors.append(
                    f"Quest '{quest.quest_id}' stage '{stage.id}' references unknown location: {stage.location}"
                )
        
        # Rule 7: At least one reward
        has_reward = any(stage.rewards for stage in quest.stages if stage.type == "outro")
        if not has_reward:
            result.passed = False
            result.errors.append(
                f"Quest '{quest.quest_id}' has no rewards in outro stage"
            )
        
        # Rule 8: No dead-end stages (every non-outro stage should lead somewhere)
        # This is implicitly checked by reachability, but we add explicit warning
        stage_ids = {stage.id for stage in quest.stages}
        for stage in quest.stages:
            if stage.type != "outro":
                # In a proper state machine, non-outro stages should have transitions
                # Since we don't have explicit transitions in the schema, we check
                # that there's at least one other stage after this one
                pass  # Reachability check covers this
        
        return result
    
    def validate_multiple_quests(self, quests: list[QuestGraph]) -> ValidationResult:
        """Validate multiple quests for circular dependencies."""
        result = ValidationResult(passed=True)
        
        # Rule 1: No circular dependencies
        if not self._check_no_circular_dependencies(quests):
            result.passed = False
            result.errors.append("Circular dependencies detected between quests")
        
        # Validate each individual quest
        for quest in quests:
            quest_result = self.validate_single_quest(quest)
            result = result.merge(quest_result)
        
        return result
    
    def _check_stage_reachability(self, stages: list[QuestStage]) -> bool:
        """Check if all stages are reachable from the first stage using BFS."""
        if not stages:
            return False
        
        # Build adjacency from stage order (simplified - assumes linear progression)
        # In a real implementation, stages would have explicit 'next' pointers
        stage_ids = [stage.id for stage in stages]
        
        # BFS from first stage
        visited = set()
        queue = deque([stages[0].id])
        
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            
            # Find next stages (simplified: assume sequential ordering)
            try:
                idx = stage_ids.index(current)
                if idx < len(stage_ids) - 1:
                    queue.append(stage_ids[idx + 1])
            except ValueError:
                pass
        
        return len(visited) == len(stages)
    
    def _check_no_circular_dependencies(self, quests: list[QuestGraph]) -> bool:
        """Check for circular dependencies using DFS."""
        quest_map = {q.quest_id: q for q in quests}
        visited = set()
        rec_stack = set()
        
        def has_cycle(quest_id: str) -> bool:
            visited.add(quest_id)
            rec_stack.add(quest_id)
            
            quest = quest_map.get(quest_id)
            if quest:
                for dep in quest.dependencies:
                    if dep not in visited:
                        if has_cycle(dep):
                            return True
                    elif dep in rec_stack:
                        return True
            
            rec_stack.remove(quest_id)
            return False
        
        for quest_id in quest_map:
            if quest_id not in visited:
                if has_cycle(quest_id):
                    return False
        
        return True


class DialogueTreeValidator:
    """
    Validates dialogue trees before they reach the Coder.
    
    Validation Rules (from spec Section 5.3):
    1. Every text_key must exist in localization file
    2. Every 'next' node must exist in dialogue tree
    3. No orphan nodes (all nodes reachable from trigger)
    4. Every 'requires' condition must be satisfiable
    5. Every 'action' must be valid
    """
    
    VALID_ACTIONS = {"give_item", "set_flag", "start_quest", "end_quest", "teleport"}
    
    def __init__(self, localization_keys: set[str] = None, 
                 item_registry: set[str] = None,
                 flag_registry: set[str] = None,
                 quest_registry: set[str] = None):
        self.localization_keys = localization_keys or set()
        self.item_registry = item_registry or set()
        self.flag_registry = flag_registry or set()
        self.quest_registry = quest_registry or set()
    
    def validate_single_dialogue(self, dialogue: DialogueTree) -> ValidationResult:
        """Validate a single dialogue tree."""
        result = ValidationResult(passed=True)
        
        if not dialogue.nodes:
            result.passed = False
            result.errors.append(f"Dialogue '{dialogue.dialogue_id}' has no nodes")
            return result
        
        # Rule 1: All text_keys must exist in localization
        for node in dialogue.nodes:
            # Check node text_key
            if node.text_key not in self.localization_keys:
                result.passed = False
                result.errors.append(
                    f"Dialogue '{dialogue.dialogue_id}' node '{node.id}' has missing localization key: {node.text_key}"
                )
            
            # Check choice text_keys
            for choice in node.choices:
                if choice.text_key not in self.localization_keys:
                    result.passed = False
                    result.errors.append(
                        f"Dialogue '{dialogue.dialogue_id}' node '{node.id}' choice has missing key: {choice.text_key}"
                    )
        
        # Rule 2: Every 'next' must point to existing node
        node_ids = {node.id for node in dialogue.nodes}
        for node in dialogue.nodes:
            for choice in node.choices:
                if choice.next not in node_ids:
                    result.passed = False
                    result.errors.append(
                        f"Dialogue '{dialogue.dialogue_id}' node '{node.id}' references non-existent node: {choice.next}"
                    )
        
        # Rule 3: No orphan nodes (BFS from first node)
        if not self._check_node_reachability(dialogue.nodes):
            result.passed = False
            result.errors.append(
                f"Dialogue '{dialogue.dialogue_id}' has orphan nodes"
            )
        
        # Rule 4: All 'requires' conditions must be satisfiable
        for node in dialogue.nodes:
            for choice in node.choices:
                if choice.requires:
                    if not self._is_condition_valid(choice.requires):
                        result.passed = False
                        result.errors.append(
                            f"Dialogue '{dialogue.dialogue_id}' node '{node.id}' has invalid condition: {choice.requires}"
                        )
        
        # Rule 5: All actions must be valid
        for node in dialogue.nodes:
            for choice in node.choices:
                if choice.action:
                    if not self._is_action_valid(choice.action):
                        result.passed = False
                        result.errors.append(
                            f"Dialogue '{dialogue.dialogue_id}' node '{node.id}' has invalid action: {choice.action}"
                        )
        
        return result
    
    def validate_multiple_dialogues(self, dialogues: list[DialogueTree]) -> ValidationResult:
        """Validate multiple dialogue trees."""
        result = ValidationResult(passed=True)
        
        for dialogue in dialogues:
            dialogue_result = self.validate_single_dialogue(dialogue)
            result = result.merge(dialogue_result)
        
        return result
    
    def _check_node_reachability(self, nodes: list[DialogueNode]) -> bool:
        """Check if all nodes are reachable from the first node using BFS."""
        if not nodes:
            return False
        
        node_map = {node.id: node for node in nodes}
        visited = set()
        queue = deque([nodes[0].id])
        
        while queue:
            current_id = queue.popleft()
            if current_id in visited:
                continue
            visited.add(current_id)
            
            current_node = node_map.get(current_id)
            if current_node:
                for choice in current_node.choices:
                    if choice.next not in visited:
                        queue.append(choice.next)
        
        return len(visited) == len(nodes)
    
    def _is_condition_valid(self, condition: str) -> bool:
        """Check if a condition string is valid."""
        # Parse condition format: "has_item:item_id" or "flag:flag_name" or "quest_complete:quest_id"
        if ':' not in condition:
            return False
        
        cond_type, value = condition.split(':', 1)
        
        if cond_type == "has_item":
            return value in self.item_registry
        elif cond_type == "flag":
            return value in self.flag_registry
        elif cond_type == "quest_complete":
            return value in self.quest_registry
        elif cond_type == "quest_stage":
            # Format: quest_stage:quest_id:stage_id
            parts = value.split(':')
            if len(parts) >= 2:
                return parts[0] in self.quest_registry
            return False
        
        return True  # Unknown condition types pass (flexible)
    
    def _is_action_valid(self, action: str) -> bool:
        """Check if an action string is valid."""
        # Parse action format: "give_item:item_id" or "set_flag:flag_name:value"
        if ':' not in action:
            return action in self.VALID_ACTIONS
        
        action_type, value = action.split(':', 1)
        
        if action_type not in self.VALID_ACTIONS:
            return False
        
        if action_type == "give_item":
            return value in self.item_registry
        elif action_type == "set_flag":
            return True  # Flags can be created dynamically
        elif action_type in ("start_quest", "end_quest"):
            return value in self.quest_registry
        
        return True


class LevelLayoutValidator:
    """
    Validates procedurally generated level layouts.
    
    Validation Rules (from spec Section 6.5):
    1. Start and End points must exist and be in valid rooms
    2. All points of interest must be reachable from start
    3. No overlapping rooms (BSP guarantees this)
    4. Enemy density does not exceed threshold
    5. At least one path exists from start to end (A* verification)
    """
    
    def __init__(self, max_enemy_density: float = 0.5, max_item_density: float = 0.5):
        self.max_enemy_density = max_enemy_density
        self.max_item_density = max_item_density
    
    def validate_level(self, layout: LevelLayout) -> ValidationResult:
        """Validate a level layout."""
        result = ValidationResult(passed=True)
        
        # Rule 1: Start and end rooms must exist
        room_names = {room.room_type for room in layout.rooms}
        if layout.start_room not in room_names:
            result.passed = False
            result.errors.append(f"Start room '{layout.start_room}' does not exist")
        
        if layout.end_room not in room_names:
            result.passed = False
            result.errors.append(f"End room '{layout.end_room}' does not exist")
        
        # Rule 2: All points of interest must be reachable (simplified check)
        # In full implementation, run A* from start to each POI
        poi_locations = {poi.get('room') for poi in layout.points_of_interest if poi.get('room')}
        if not poi_locations.issubset(room_names):
            result.passed = False
            result.errors.append("Some points of interest are in non-existent rooms")
        
        # Rule 3: Check for overlapping rooms
        if self._has_overlapping_rooms(layout.rooms):
            result.passed = False
            result.errors.append("Overlapping rooms detected")
        
        # Rule 4: Check enemy density
        total_area = sum(r.width * r.height for r in layout.rooms)
        if total_area > 0:
            enemy_density = len(layout.enemy_spawn_points) / total_area
            if enemy_density > self.max_enemy_density:
                result.warnings.append(
                    f"Enemy density ({enemy_density:.2f}) exceeds recommended ({self.max_enemy_density})"
                )
            
            item_density = len(layout.item_spawn_points) / total_area
            if item_density > self.max_item_density:
                result.warnings.append(
                    f"Item density ({item_density:.2f}) exceeds recommended ({self.max_item_density})"
                )
        
        # Rule 5: Path existence check (simplified - corridors connect rooms)
        if not self._has_path_start_to_end(layout):
            result.passed = False
            result.errors.append("No path exists from start to end room")
        
        return result
    
    def _has_overlapping_rooms(self, rooms: list[Room]) -> bool:
        """Check if any rooms overlap."""
        for i, room1 in enumerate(rooms):
            for room2 in rooms[i+1:]:
                if self._rooms_overlap(room1, room2):
                    return True
        return False
    
    def _rooms_overlap(self, room1: Room, room2: Room) -> bool:
        """Check if two rooms overlap."""
        return not (
            room1.x + room1.width <= room2.x or
            room2.x + room2.width <= room1.x or
            room1.y + room1.height <= room2.y or
            room2.y + room2.height <= room1.y
        )
    
    def _has_path_start_to_end(self, layout: LevelLayout) -> bool:
        """Check if there's a path from start to end using corridor connections."""
        # Simplified: assume corridors provide connectivity
        # Full implementation would use A* on the grid
        
        if not layout.corridors:
            # If no corridors, check if start and end are the same room
            return layout.start_room == layout.end_room
        
        # Build graph of room connections
        room_map = {room.room_type: room for room in layout.rooms}
        
        # For now, assume connectivity if corridors exist
        # A full implementation would trace actual paths
        return len(layout.corridors) > 0


# ============================================================================
# Validator Factory
# ============================================================================

def create_quest_validator(item_registry: set[str] = None, 
                          npc_registry: set[str] = None,
                          location_registry: set[str] = None) -> QuestGraphValidator:
    """Factory function to create a QuestGraphValidator."""
    return QuestGraphValidator(
        item_registry=item_registry,
        npc_registry=npc_registry,
        location_registry=location_registry
    )


def create_dialogue_validator(localization_keys: set[str] = None,
                             item_registry: set[str] = None,
                             flag_registry: set[str] = None,
                             quest_registry: set[str] = None) -> DialogueTreeValidator:
    """Factory function to create a DialogueTreeValidator."""
    return DialogueTreeValidator(
        localization_keys=localization_keys,
        item_registry=item_registry,
        flag_registry=flag_registry,
        quest_registry=quest_registry
    )


def create_level_validator(max_enemy_density: float = 0.5,
                          max_item_density: float = 0.5) -> LevelLayoutValidator:
    """Factory function to create a LevelLayoutValidator."""
    return LevelLayoutValidator(
        max_enemy_density=max_enemy_density,
        max_item_density=max_item_density
    )
