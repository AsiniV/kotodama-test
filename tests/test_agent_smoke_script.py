"""Offline pytest wrapper around scripts/agent_smoke.py (Phase 3: agent contracts).

Guarantees the DONE criterion for the phase — "agent_smoke.py passes offline for
all agents" — inside the regular test suite, without GPU / LLM server / network.

The smoke script monkeypatches ``LLMClient._complete`` process-wide, so it is
executed in a fresh subprocess to keep the rest of the suite's fixtures clean.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agent_smoke.py"


def _godot_present() -> bool:
    """True if a real Godot binary is on PATH (playtester would then be live)."""
    return (
        bool(os.environ.get("GODOT_HEADLESS_PATH"))
        or os.environ.get("KOTODAMA_USE_GODOT") == "1"
        or shutil_which("godot") is not None
    )


def shutil_which(name: str) -> str | None:
    import shutil

    return shutil.which(name)


@pytest.mark.skipif(_godot_present(), reason="real Godot binary present; smoke run would not be offline-deterministic")
def test_agent_smoke_all_agents_pass_offline() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, f"agent_smoke.py failed:\n{proc.stdout}\n{proc.stderr}"
    # every registered agent must report OK and the final tally must be clean
    assert "agents produced validated outputs." in proc.stdout
    assert "[FAIL]" not in proc.stdout
    assert "[BAD]" not in proc.stdout
    ok_count = proc.stdout.count("[OK ]")
    assert ok_count == 11, f"expected 11 OK agents, got {ok_count}:\n{proc.stdout}"


def test_agent_smoke_single_agent_selection() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "designer"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, f"agent_smoke.py designer failed:\n{proc.stdout}\n{proc.stderr}"
    assert "[OK ] designer" in proc.stdout
    assert "1/1 agents produced validated outputs." in proc.stdout


def test_agent_smoke_unknown_agent_is_error() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "does-not-exist"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(ROOT),
    )
    assert proc.returncode == 2
    assert "unknown agent" in proc.stderr
