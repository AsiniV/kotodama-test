"""
Coder Agent - Writes clean GDScript for assigned modules.
Does NOT touch Core Engine. Integrates quests, dialogues, assets, and levels.
"""

import logging
from backend.agents.base import BaseAgent
from backend.schemas.agent_schemas import CoderInput, CoderOutput

logger = logging.getLogger("kotodama.agents.coder")


class CoderAgent(BaseAgent[CoderOutput]):
    """
    Coder Agent responsible for generating GDScript code for modules.
    
    Input: ArchitecturePlan + optional QuestGraphs + DialogueTrees + AssetPaths + LevelLayout
    Output: GeneratedFile list with complete module implementations
    
    CRITICAL: Never modifies Core Engine files. Only creates/updates module files.
    """
    
    def __init__(self, model_name: str = "qwen2.5-coder:32b", temperature: float = 0.15):
        super().__init__(model_name=model_name, temperature=temperature)
    
    def _get_system_prompt(self) -> str:
        return """You are an expert Godot 4.3 GDScript Developer AI.
Your task is to write clean, production-ready GDScript code for game modules.

CRITICAL RULES:
1. NEVER modify Core Engine files (scene_manager.gd, input_system.gd, signal_bus.gd, state_machine.gd, physics.gd, ui_framework.gd)
2. ONLY create/modify files in modules/ directory
3. All inter-module communication MUST use signals with `module_` prefix
4. Use ResourceLoader.exists() for asset checks - NEVER use preload() to avoid parse errors
5. Follow Godot 4.3 best practices (typed variables, proper node naming, signal usage)
6. Code must be human-readable and well-commented
7. Every module must register its signals via Global Signal Bus

CODE STYLE:
- Use GDScript 2.0 syntax (typed variables: var health: int = 100)
- Follow Godot naming conventions (snake_case for variables/functions, PascalCase for classes)
- Include docstrings for public methods
- Use @export for editor-exposed variables
- Use @onready for cached node references

ASSET INTEGRATION:
- Check asset existence: if ResourceLoader.exists(asset_path): ...
- Load assets at runtime: var texture = load(asset_path)
- Never assume assets exist - always check first

QUEST INTEGRATION:
- Quest stages trigger on specific conditions
- Use signals to communicate quest progress: module_quest_stage_completed.emit(quest_id, stage_id)
- Track quest state in QuestManager singleton

DIALOGUE INTEGRATION:
- Dialogues triggered by interactables or quest stages
- Use tr() for all text strings (localization support)
- Dialogue choices can trigger actions: give_item, set_flag, start_quest

LEVEL INTEGRATION:
- Convert LevelLayout data into actual scene nodes
- Place enemies, items, NPCs at spawn points
- Set up navigation meshes if required

SAVE SYSTEM INTEGRATION:
- If save_system_required is true, implement serialize()/deserialize() methods
- Save: player position, health, inventory, quest states, dialogue flags, world state
- Load: restore all saved state gracefully

OUTPUT FORMAT:
Return a list of GeneratedFile objects with:
- path: relative path from project root (e.g., "modules/player_controller/player_controller.gd")
- content: complete file content
- file_type: "gdscript", "tscn", "json", or "import"
- module_id: which module this file belongs to

Generate COMPLETE, WORKING CODE - no placeholders or TODOs."""

    async def execute(self, input_data: CoderInput) -> CoderOutput:
        """
        Execute the Coder agent.
        
        Args:
            input_data: CoderInput with architecture plan and optional content data
            
        Returns:
            CoderOutput with generated files
        """
        prompt = self._build_prompt(input_data)
        result = await self._call_llm(prompt, CoderOutput)
        
        logger.info(f"Generated {len(result.files)} files for {len(result.modules_created)} modules")
        return result
    
    def _build_prompt(self, coder_input: CoderInput) -> str:
        """Build the prompt for the LLM."""
        arch = coder_input.architecture_plan
        
        prompt = f"""Generate complete GDScript code based on the following Architecture Plan:

SCENE TREE: {arch.scene_tree}
REQUIRED MODULES: {arch.required_modules}
SIGNAL CONTRACTS: {arch.signal_contracts}
ASSET SLOTS NEEDED: {arch.asset_slots_needed}
SAVE SYSTEM REQUIRED: {arch.save_system_required}
"""
        
        if coder_input.quest_graphs:
            prompt += f"\nQUEST GRAPHS: {len(coder_input.quest_graphs)} quests\n"
            for quest in coder_input.quest_graphs[:3]:  # Limit to first 3 for brevity
                prompt += f"- {quest.quest_id}: {quest.title} ({len(quest.stages)} stages)\n"
        
        if coder_input.dialogue_trees:
            prompt += f"\nDIALOGUE TREES: {len(coder_input.dialogue_trees)} dialogues\n"
            for dialogue in coder_input.dialogue_trees[:3]:
                prompt += f"- {dialogue.dialogue_id}: NPC {dialogue.npc_id} ({len(dialogue.nodes)} nodes)\n"
        
        if coder_input.asset_paths:
            prompt += f"\nASSET PATHS: {coder_input.asset_paths}\n"
        
        if coder_input.level_layout:
            prompt += f"\nLEVEL LAYOUT: {coder_input.level_layout}\n"
        
        prompt += """
Generate COMPLETE, WORKING GDScript code for all required modules.
Each file must be fully implemented with no placeholders.
Follow all rules in the system prompt."""
        
        return prompt


# Singleton instance
_coder_agent = None


def get_coder_agent() -> CoderAgent:
    """Get singleton instance of CoderAgent."""
    global _coder_agent
    if _coder_agent is None:
        _coder_agent = CoderAgent()
    return _coder_agent
