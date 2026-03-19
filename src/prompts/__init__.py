from pathlib import Path
from string import Template

_PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str) -> Template:
    """Load a prompt template from src/prompts/<name>.txt."""
    path = _PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return Template(path.read_text())
