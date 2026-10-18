"""Local JSON state store for the simulated AWS account.

Everything the control plane knows (roles, repositories, task definitions,
tasks) lives in one JSON file so every verb is inspectable and reproducible.
No cloud service is contacted.
"""

import json
from pathlib import Path

ACCOUNT_ID = "000000000000"
PARTITION = "simaws"
REGION = "local"


def empty_state() -> dict:
    """Return a fresh account state with every section present."""
    return {
        "version": 1,
        "iam": {"roles": {}},
        "ecr": {"repositories": {}},
        "ecs": {"task_definitions": {}, "tasks": {}},
    }


def load_state(path: Path) -> dict:
    """Load the account state, or a fresh state when the file does not exist."""
    location = Path(path)
    if not location.exists():
        return empty_state()
    return json.loads(location.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict) -> None:
    """Write the account state as readable JSON, creating parent directories."""
    location = Path(path)
    location.parent.mkdir(parents=True, exist_ok=True)
    location.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
