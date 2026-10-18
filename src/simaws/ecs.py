"""Simulated ECS: task definitions, run-task with IAM enforcement, task logs.

run-task mirrors the real service's behavior of authorizing before starting:
the task's role must grant the image pull on that exact repository and log
writes to that exact log group, the image digest must exist in the registry,
and the network placement must pass validation, or the task is denied and
nothing executes. The simulated runtime then executes the verified task
entrypoint in place and captures its output to a task log; with a real
container runtime the same task definition would docker-run the pulled image.
"""

import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from simaws import ecr
from simaws.iam import IamError, get_role, role_allows
from simaws.network import validate_network
from simaws.state import ACCOUNT_ID, PARTITION, REGION


class EcsError(RuntimeError):
    """Raised when an ECS verb cannot do what was asked."""

LOG_GROUP = "/simaws/risk-service"

# Actions the task role must grant, exactly: pull the service image, write the
# service logs. Anything less is denied; the linter guarantees nothing broader
# can be attached either.
PULL_ACTIONS = (
    "ecr:GetAuthorizationToken",
    "ecr:BatchGetImage",
    "ecr:GetDownloadUrlForLayer",
)
LOGS_WRITE_ACTIONS = (
    "logs:CreateLogStream",
    "logs:PutLogEvents",
)

# A scripted task finishes in about a second; a live-model task can sit through
# a cold model load, so the ceiling stays generous.
SERVICE_TIMEOUT_SECONDS = 900.0


def log_group_arn() -> str:
    """The simulated ARN of the service's log group."""
    return f"arn:{PARTITION}:logs:{REGION}:{ACCOUNT_ID}:log-group:{LOG_GROUP}"


def task_arn(task_id: str) -> str:
    """The simulated ARN for a task run."""
    return f"arn:{PARTITION}:ecs:{REGION}:{ACCOUNT_ID}:task/risk-service/{task_id}"


def register_task_definition(
    state: dict,
    family: str,
    image_ref: str,
    task_role: str,
    env: dict[str, str] | None = None,
) -> dict:
    """Register (or idempotently replace) the family's task definition."""
    if ":" not in image_ref:
        raise EcsError(
            f"image ref '{image_ref}' must be repository:tag; the registry is digest-addressed"
        )
    definition = {
        "family": family,
        "image": image_ref,
        "task_role": task_role,
        "env": dict(env or {}),
    }
    state["ecs"]["task_definitions"][family] = definition
    return definition


def _authorization_gaps(role: dict, repository: str) -> list[str]:
    """Every required action the role does not grant on the exact resource."""
    gaps = [
        action
        for action in PULL_ACTIONS
        if not role_allows(role, action, ecr.repository_arn(repository))
    ]
    gaps += [
        action
        for action in LOGS_WRITE_ACTIONS
        if not role_allows(role, action, log_group_arn())
    ]
    return gaps


def run_task(
    state: dict,
    family: str,
    container_command: list[str],
    network_config: dict,
    state_dir: Path,
    workdir: Path,
) -> dict:
    """Authorize, then execute one task run; returns the task document.

    Order matters and is the point: definition, then role, then image, then
    IAM authorization, then network validation, and only then execution. A
    denial never creates a task document.
    """
    definition = state["ecs"]["task_definitions"].get(family)
    if definition is None:
        raise EcsError(f"no task definition registered for family '{family}'")
    try:
        role = get_role(state, definition["task_role"])
    except IamError as exc:
        raise EcsError(f"cannot start task: {exc}") from exc
    repository, _, tag = definition["image"].rpartition(":")
    try:
        image = ecr.get_image(state, repository, tag)
    except ecr.EcrError as exc:
        raise EcsError(f"cannot start task: {exc}; push the image first") from exc
    gaps = _authorization_gaps(role, repository)
    if gaps:
        raise EcsError(
            f"AccessDenied: task role '{definition['task_role']}' lacks required "
            f"actions: {', '.join(gaps)}"
        )
    errors = validate_network(network_config)
    if errors:
        raise EcsError(
            "network placement invalid, task not started: " + "; ".join(errors)
        )
    placement = network_config["task"]

    task_id = uuid.uuid4().hex[:12]
    arn = task_arn(task_id)
    log_dir = Path(state_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{task_id}.log"
    started = datetime.now(timezone.utc)
    header = [
        f"task {arn}",
        f"started: {started.isoformat(timespec='seconds')}",
        f"image: {definition['image']} @ {image['digest']} ({image['packaging']})",
        f"role: {role['arn']} (image pull and log write actions verified)",
        f"placement: subnet {placement['subnet']} / security group {placement['security_group']}",
        "model endpoint: "
        f"{placement['model_endpoint']['cidr']}:{placement['model_endpoint']['port']}"
        " (simulated managed model service)",
        f"command: {' '.join(container_command)}",
        "-" * 72,
    ]
    env = {
        **os.environ,
        **definition["env"],
        "SIMAWS_TASK_ROLE": role["arn"],
        "SIMAWS_TASK_ARN": arn,
    }
    try:
        completed = subprocess.run(
            container_command,
            cwd=str(workdir),
            env=env,
            capture_output=True,
            text=True,
            timeout=SERVICE_TIMEOUT_SECONDS,
        )
        exit_code: int | None = completed.returncode
        output = completed.stdout + (completed.stderr or "")
    except subprocess.TimeoutExpired as exc:
        exit_code = None
        output = (
            f"task exceeded {SERVICE_TIMEOUT_SECONDS:.0f}s and was stopped\n{exc}"
        )
    document = {
        "task_id": task_id,
        "task_arn": arn,
        "task_definition": family,
        "image": definition["image"],
        "image_digest": image["digest"],
        "task_role": definition["task_role"],
        "subnet": placement["subnet"],
        "security_group": placement["security_group"],
        "command": container_command,
        "status": "STOPPED",
        "exit_code": exit_code,
        "log_file": str(log_path),
        "started_at": started.isoformat(timespec="seconds"),
        "stopped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    log_path.write_text("\n".join(header) + "\n" + (output or "") + "\n", encoding="utf-8")
    state["ecs"]["tasks"][task_id] = document
    return document


def get_task(state: dict, task_id: str) -> dict:
    """Return one task document; raise when the id is unknown."""
    document = state["ecs"]["tasks"].get(task_id)
    if document is None:
        raise EcsError(f"task '{task_id}' not found")
    return document
