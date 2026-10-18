"""Additional ecs branch tests: bad image refs, missing roles, task timeout."""

import json
import subprocess
from pathlib import Path

import pytest

from simaws import ecs
from simaws.ecs import EcsError
from simaws.state import empty_state

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def prepared(tmp_path):
    """Registry with a pushed image; no task role created."""
    from simaws import ecr
    from simaws.state import save_state

    state = empty_state()
    ecr.create_repository(state, "risk-service")
    ecr.push_image(
        state,
        "risk-service",
        "v1",
        source_dir=REPO_ROOT,
        images_dir=tmp_path / "images",
        use_docker=False,
    )
    save_state(tmp_path / "state.json", state)
    return tmp_path, state


def test_register_task_definition_rejects_bare_image_name():
    state = empty_state()
    with pytest.raises(EcsError, match="repository:tag"):
        ecs.register_task_definition(state, "fam", "risk-service", "role")


def test_run_task_fails_when_task_role_missing(prepared):
    tmp_path, state = prepared
    ecs.register_task_definition(
        state,
        family="risk-service",
        image_ref="risk-service:v1",
        task_role="ghost-role",
        env={},
    )
    with pytest.raises(EcsError, match="cannot start task: role 'ghost-role' not found"):
        ecs.run_task(
            state,
            "risk-service",
            ["echo", "hi"],
            network_config=json.loads(
                (REPO_ROOT / "deploy" / "network.json").read_text(encoding="utf-8")
            ),
            state_dir=tmp_path,
            workdir=REPO_ROOT,
        )


def test_run_task_records_timeout_as_stopped_with_no_exit_code(prepared, monkeypatch):
    tmp_path, state = prepared
    from simaws.iam import create_role, put_role_policy

    policy = json.loads(
        (REPO_ROOT / "deploy" / "iam-policy.json").read_text(encoding="utf-8")
    )
    create_role(state, "risk-service-task")
    put_role_policy(state, "risk-service-task", "task-policy", policy)
    ecs.register_task_definition(
        state,
        family="risk-service",
        image_ref="risk-service:v1",
        task_role="risk-service-task",
        env={},
    )

    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=900)

    monkeypatch.setattr(ecs.subprocess, "run", timed_out)
    network = json.loads(
        (REPO_ROOT / "deploy" / "network.json").read_text(encoding="utf-8")
    )
    task = ecs.run_task(
        state,
        "risk-service",
        ["echo", "hi"],
        network_config=network,
        state_dir=tmp_path,
        workdir=REPO_ROOT,
    )
    assert task["status"] == "STOPPED"
    assert task["exit_code"] is None
    log_text = Path(task["log_file"]).read_text(encoding="utf-8")
    assert "exceeded 900s" in log_text
