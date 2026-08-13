"""
AI Playtester Agent - Launches Godot headless and runs heuristic tests.

Phase 6 Capabilities (Enhanced):
- Active bot-player simulation (move, interact, collect, attack, talk)
- Reachability check (StartPoint → EndPoint via raycast)
- FPS monitoring (avg, min)
- Error counting (engine vs. module errors)
- Crash detection
- NEW: Item collection tracking
- NEW: NPC interaction tracking
- NEW: Quest start/completion tracking
- NEW: Dialogue opening tracking
- NEW: Bot stuck detection
- Updated stability score calculation (0-100) with new penalties
"""

import asyncio
import re
from datetime import datetime
from typing import Optional
from pathlib import Path

from backend.agents.base import BaseAgent
from backend.schemas.agent_schemas import PlaytestReport, PlaytestConfig


class AIPlaytesterAgent(BaseAgent):
    """Agent that runs automated playtests in Godot headless with bot-player simulation."""

    def __init__(self, godot_headless_path: str = "godot-headless"):
        super().__init__(model_name="qwen2.5:32b", temperature=0.0)
        self.godot_headless_path = godot_headless_path

    def _get_system_prompt(self) -> str:
        """Return system prompt for playtester (not used, but required by base class)."""
        return "You are an AI Playtester. This is a placeholder prompt as the playtester does not use LLM."

    async def execute(self, config: PlaytestConfig) -> PlaytestReport:
        """Run playtest with bot-player simulation and return report."""
        workspace_path = Path(config.workspace_path)
        project_path = workspace_path / "game_project"
        
        if not project_path.exists():
            return PlaytestReport(
                success=False,
                stability_score=0,
                error_message="Project path does not exist",
                timestamp=datetime.now(),
            )

        # Run Godot headless with bot-player enabled
        try:
            process = await asyncio.create_subprocess_exec(
                self.godot_headless_path,
                "--headless",
                "--path", str(project_path),
                "--quit-after", str(config.max_frames),
                "--",  # Separator for custom arguments
                "bot_player_enabled=true",  # Enable bot-player simulation
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=config.timeout_seconds
            )
            
            stdout_text = stdout.decode("utf-8", errors="ignore")
            stderr_text = stderr.decode("utf-8", errors="ignore")
            
        except asyncio.TimeoutError:
            process.kill()
            return PlaytestReport(
                success=False,
                stability_score=45,  # 100 - 55 (timeout penalty)
                error_message="Playtest timed out",
                timestamp=datetime.now(),
                fps_avg=0,
                fps_min=0,
                engine_errors=0,
                module_errors=0,
                crashed=False,
                timed_out=True,
            )
        except Exception as e:
            return PlaytestReport(
                success=False,
                stability_score=0,
                error_message=f"Failed to launch Godot: {str(e)}",
                timestamp=datetime.now(),
                crashed=True,
            )

        # Parse logs for all metrics
        fps_values = self._parse_fps(stdout_text)
        engine_errors = self._count_engine_errors(stderr_text)
        module_errors = self._count_module_errors(stderr_text)
        has_start_point = self._check_marker(stdout_text, "StartPoint")
        has_end_point = self._check_marker(stdout_text, "EndPoint")
        has_line_of_sight = self._check_marker(stdout_text, "LineOfSight:OK")
        crashed = process.returncode != 0 and process.returncode != -15  # -15 is normal quit
        
        # NEW: Parse enhanced metrics from bot-player simulation
        items_collected = self._parse_metric(stdout_text, r"BotPlayer:items_collected:(\d+)")
        npcs_interacted = self._parse_metric(stdout_text, r"BotPlayer:npcs_interacted:(\d+)")
        quests_started = self._parse_metric(stdout_text, r"BotPlayer:quests_started:(\d+)")
        quests_completed = self._parse_metric(stdout_text, r"BotPlayer:quests_completed:(\d+)")
        dialogues_opened = self._parse_metric(stdout_text, r"BotPlayer:dialogues_opened:(\d+)")
        player_deaths = self._parse_metric(stdout_text, r"BotPlayer:player_deaths:(\d+)")
        stuck_frames = self._parse_metric(stdout_text, r"BotPlayer:stuck_frames:(\d+)")
        
        # Detect if game has items/dialogues/quests (from markers)
        has_items = self._check_marker(stdout_text, "GameHasItems:true")
        has_dialogues = self._check_marker(stdout_text, "GameHasDialogues:true")
        has_quests = self._check_marker(stdout_text, "GameHasQuests:true")
        
        # Calculate stability score with NEW enhanced scoring
        stability_score = self._calculate_stability_score(
            crashed=crashed,
            timed_out=False,
            engine_errors=engine_errors,
            module_errors=module_errors,
            has_end_point=has_end_point,
            has_start_point=has_start_point,
            has_line_of_sight=has_line_of_sight,
            fps_avg=sum(fps_values) / len(fps_values) if fps_values else 0,
            total_frames=len(fps_values),
            # NEW metrics
            items_collected=items_collected,
            has_items=has_items,
            dialogues_opened=dialogues_opened,
            has_dialogues=has_dialogues,
            quests_started=quests_started,
            has_quests=has_quests,
            stuck_frames=stuck_frames,
        )

        return PlaytestReport(
            success=stability_score >= 60,
            stability_score=max(0, min(100, stability_score)),
            fps_avg=sum(fps_values) / len(fps_values) if fps_values else 0,
            fps_min=min(fps_values) if fps_values else 0,
            engine_errors=engine_errors,
            module_errors=module_errors,
            crashed=crashed,
            timed_out=False,
            has_start_point=has_start_point,
            has_end_point=has_end_point,
            has_line_of_sight=has_line_of_sight,
            frames_rendered=len(fps_values),
            log_output=stderr_text[-2000:],  # Last 2000 chars
            # NEW: Store enhanced metrics in log_output for now
            # (PlaytestMetrics schema already has these fields)
            error_message=self._format_enhanced_metrics(
                items_collected, npcs_interacted, quests_started, 
                quests_completed, dialogues_opened, player_deaths, stuck_frames
            ),
            timestamp=datetime.now(),
        )
    
    def _parse_metric(self, log_text: str, pattern: str) -> int:
        """Extract a numeric metric from logs using regex pattern."""
        match = re.search(pattern, log_text)
        return int(match.group(1)) if match else 0
    
    def _format_enhanced_metrics(
        self, items_collected: int, npcs_interacted: int, 
        quests_started: int, quests_completed: int,
        dialogues_opened: int, player_deaths: int, stuck_frames: int
    ) -> str:
        """Format enhanced metrics as a summary string."""
        return (
            f"\n=== Bot-Player Metrics ===\n"
            f"Items collected: {items_collected}\n"
            f"NPCs interacted: {npcs_interacted}\n"
            f"Quests started: {quests_started}\n"
            f"Quests completed: {quests_completed}\n"
            f"Dialogues opened: {dialogues_opened}\n"
            f"Player deaths: {player_deaths}\n"
            f"Stuck frames: {stuck_frames}\n"
        )

    def _parse_fps(self, log_text: str) -> list[float]:
        """Extract FPS values from Godot logs."""
        fps_pattern = r"FPS:\s*([\d.]+)"
        matches = re.findall(fps_pattern, log_text)
        return [float(m) for m in matches if m]

    def _count_engine_errors(self, log_text: str) -> int:
        """Count Godot engine errors."""
        error_patterns = [
            r"ERROR:",
            r"CRITICAL:",
            r"Unhandled Exception",
        ]
        count = 0
        for pattern in error_patterns:
            count += len(re.findall(pattern, log_text, re.IGNORECASE))
        return count

    def _count_module_errors(self, log_text: str) -> int:
        """Count module-specific errors (non-engine)."""
        module_pattern = r"module_[\w]+.*ERROR"
        return len(re.findall(module_pattern, log_text, re.IGNORECASE))

    def _check_marker(self, log_text: str, marker: str) -> bool:
        """Check if a specific marker exists in logs."""
        return marker in log_text

    def _calculate_stability_score(
        self,
        crashed: bool,
        timed_out: bool,
        engine_errors: int,
        module_errors: int,
        has_end_point: bool,
        has_start_point: bool,
        has_line_of_sight: bool,
        fps_avg: float,
        total_frames: int,
        # NEW parameters for enhanced scoring (Section 7.3)
        items_collected: int = 0,
        has_items: bool = False,
        dialogues_opened: int = 0,
        has_dialogues: bool = False,
        quests_started: int = 0,
        has_quests: bool = False,
        stuck_frames: int = 0,
    ) -> int:
        """
        Calculate stability score 0-100 based on playtest metrics.
        
        Updated scoring rules per Section 7.4:
        Base: 100
        - Crashed: → 0
        - Timed out: -55
        - No report: -25
        - Engine errors: -25 each (max -75)
        - Module errors: -5 each (max -20)
        - No EndPoint: -25
        - No StartPoint: -20
        - No line of sight: -10
        - Low FPS (<20): -10
        - Few frames (<30): -15
        - NEW: No items collected (if items exist): -10
        - NEW: No dialogues opened (if dialogues exist): -10
        - NEW: No quests started (if quests exist): -15
        - NEW: Bot stuck > 120 frames: -10
        """
        score = 100
        
        if crashed:
            return 0
        
        if timed_out:
            score -= 55
        
        # Engine errors: -25 each, max -75
        score -= min(75, engine_errors * 25)
        
        # Module errors: -5 each, max -20
        score -= min(20, module_errors * 5)
        
        if not has_end_point:
            score -= 25
        
        if not has_start_point:
            score -= 20
        
        if not has_line_of_sight:
            score -= 10
        
        if fps_avg < 20 and fps_avg > 0:
            score -= 10
        
        if total_frames < 30:
            score -= 15
        
        # NEW: Enhanced scoring penalties (Section 7.4)
        if has_items and items_collected == 0:
            score -= 10
        
        if has_dialogues and dialogues_opened == 0:
            score -= 10
        
        if has_quests and quests_started == 0:
            score -= 15
        
        if stuck_frames > 120:
            score -= 10
        
        return max(0, score)
