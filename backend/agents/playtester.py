"""
AI Playtester Agent - Launches Godot headless and runs heuristic tests.

MVP Capabilities:
- Reachability check (StartPoint → EndPoint via raycast)
- FPS monitoring (avg, min)
- Error counting (engine vs. module errors)
- Crash detection
- Stability score calculation (0-100)
"""

import asyncio
import re
from datetime import datetime
from typing import Optional
from pathlib import Path

from backend.agents.base import BaseAgent
from backend.schemas.agent_schemas import PlaytestReport, PlaytestConfig


class AIPlaytesterAgent(BaseAgent):
    """Agent that runs automated playtests in Godot headless."""

    def __init__(self, godot_headless_path: str = "godot-headless"):
        super().__init__(name="AI Playtester", temperature=0.0)
        self.godot_headless_path = godot_headless_path

    async def execute(self, config: PlaytestConfig) -> PlaytestReport:
        """Run playtest and return report."""
        workspace_path = Path(config.workspace_path)
        project_path = workspace_path / "game_project"
        
        if not project_path.exists():
            return PlaytestReport(
                success=False,
                stability_score=0,
                error_message="Project path does not exist",
                timestamp=datetime.now(),
            )

        # Run Godot headless
        try:
            process = await asyncio.create_subprocess_exec(
                self.godot_headless_path,
                "--headless",
                "--path", str(project_path),
                "--quit-after", str(config.max_frames),
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

        # Parse logs
        fps_values = self._parse_fps(stdout_text)
        engine_errors = self._count_engine_errors(stderr_text)
        module_errors = self._count_module_errors(stderr_text)
        has_start_point = self._check_marker(stdout_text, "StartPoint")
        has_end_point = self._check_marker(stdout_text, "EndPoint")
        has_line_of_sight = self._check_marker(stdout_text, "LineOfSight:OK")
        crashed = process.returncode != 0 and process.returncode != -15  # -15 is normal quit
        
        # Calculate stability score
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
            timestamp=datetime.now(),
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
    ) -> int:
        """Calculate stability score 0-100 based on playtest metrics."""
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
        
        return max(0, score)
