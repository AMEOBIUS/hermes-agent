import sys
import os
import json
import logging
from pathlib import Path
import asyncio

logger = logging.getLogger(__name__)

# Resolve real path of the project profile dir dynamically
PRODUCERS_DIR = Path("/home/ameobius/projects/security-workstation/.hermes/profiles/producers")
if not PRODUCERS_DIR.is_dir():
    PRODUCERS_DIR = Path.home() / ".hermes" / "profiles" / "producers"

# Dynamically load the prompt_doctor module
PROMPT_DOCTOR_SCRIPT = PRODUCERS_DIR / "scripts" / "prompt_doctor.py"

def run_prompt_doctor_offline(prompt: str, goal: str, failure: str) -> str:
    """Invokes local offline logic from prompt_doctor.py directly."""
    try:
        sys.path.insert(0, str(PRODUCERS_DIR / "scripts"))
        import prompt_doctor
        # Force reload in case it was modified
        import importlib
        importlib.reload(prompt_doctor)
        return prompt_doctor.run_doctor(prompt, goal, failure)
    except Exception as e:
        logger.error(f"Failed to run offline prompt doctor helper: {e}")
        # Simplistic minimal inline fallback if import fails
        return f"диагноз - не удалось импортировать локальный анализатор: {str(e)}\nновый компактный промпт - {prompt}\nпорядок тегов - жанр -> стиль -> вайб -> чистый микс"
