"""Tests for the simaws ECR registry and ECS run-task with IAM enforcement.

Seams: the registry/ecs module functions and the CLI. The task runs the real
riskservice entrypoint as a subprocess against the scripted backend, offline.
"""

import json
import shutil
import re
import sys
from pathlib import Path

import pytest

from simaws import ecr, ecs
from simaws.cli import main
from simaws.ecr import EcrError
from simaws.ecs import EcsError
from simaws.iam import create_role, put_role_policy
from simaws.state import empty_state, load_state, save_state

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_FILE = REPO_ROOT / "deploy" / "iam-policy.json"
NETWORK_CONFIG = json.loads((REPO_ROOT / "deploy" / "network.json").read_text(encoding="utf-8"))
FROZEN_INPUT = REPO_ROOT / "deploy" / "input" / "test_input.json"

PULL_ONLY_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "PullServiceImage",
            "Effect": "Allow",
            "Action": ["ecr:GetAuthorizationToken", "ecr:BatchGetImage"],
            "Resource": ["arn:simaws:ecr:local:000000000000:repository/risk-service"],
            "justification": "pull only; logs deliberately not granted for the denial test",
        }
    ],
}


@pytest.fixture
def env(tmp_path):
    """A prepared account: scoped role, repository, pushed image, task def."""
    state = empty_state()
    policy = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    create_role(state, "risk-service-task")
    put_role_policy(state, "risk-service-task", "task-policy", policy)
    ecr.create_repository(state, "risk-service")
    ecr.push_image(
        state,
        "risk-service",
        "v1",
        source_dir=REPO_ROOT,
        images_dir=tmp_path / "images",
        use_docker=False,
    )
    ecs.register_task_definition(
        state,
        family="risk-service",
        image_ref="risk-service:v1",
        task_role="risk-service-task",
        env={"RISKSERVICE_TEST_MARK": "1"},
    )
    save_state(tmp_path / "state.json", state)
    return tmp_path


def service_command() -> list[str]:
    return [
        sys.executable,
        "-m",
        "riskservice",
        "--input",
        str(FROZEN_INPUT),
        "--backend",
        "scripted",
    ]


def test_push_image_records_digest_and_artifact(env):
    state = load_state(env / "state.json")
    image = state["ecr"]["repositories"]["risk-service"]["images"]["v1"]
    assert image["digest"].startswith("sha256:")
    assert len(image["digest"]) == len("sha256:") + 64
    assert (env / "images" / image["artifact"]).exists()
    assert image["packaging"] == "source-archive"
    assert image["size_bytes"] > 0


def test_push_image_is_deterministic_and_updates_same_tag(env):
    state = load_state(env / "state.json")
    again = ecr.push_image(
        state,
        "risk-service",
        "v1",
        source_dir=REPO_ROOT,
        images_dir=env / "images",
        use_docker=False,
    )
    assert again["digest"] == state["ecr"]["repositories"]["risk-service"]["images"]["v1"]["digest"]


def test_push_image_requires_existing_repository(tmp_path):
    state = empty_state()
    with pytest.raises(EcrError):
        ecr.push_image(
            state,
            "ghost-repo",
            "v1",
            source_dir=REPO_ROOT,
            images_dir=tmp_path / "images",
            use_docker=False,
        )


def test_package_source_excludes_junk_and_is_stable(tmp_path):
    tree = tmp_path / "tree"
    (tree / "pkg").mkdir(parents=True)
    (tree / "pkg" / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tree / "README.md").write_text("hello\n", encoding="utf-8")
    junk = tmp_path / "junk-tree"
    shutil.copytree(tree, junk)
    (junk / "pkg" / "__pycache__").mkdir()
    (junk / "pkg" / "__pycache__" / "mod.cpython-312.pyc").write_bytes(b"junk")
    (junk / ".venv").mkdir()
    (junk / ".venv" / "leftover.txt").write_text("junk", encoding="utf-8")
    clean_digest = ecr.package_source(tree, tmp_path / "clean.tar.gz")
    junk_digest = ecr.package_source(junk, tmp_path / "junk.tar.gz")
    assert clean_digest == junk_digest


def test_resolve_use_docker_auto_and_explicit():
    assert ecr.resolve_use_docker(None, which=lambda name: "/bin/docker") is True
    assert ecr.resolve_use_docker(None, which=lambda name: None) is False
    assert ecr.resolve_use_docker(False, which=lambda name: "/bin/docker") is False
    assert ecr.resolve_use_docker(True, which=lambda name: None) is True


def test_run_task_happy_path_runs_service_and_captures_log(env):
    state = load_state(env / "state.json")
    task = ecs.run_task(
        state,
        "risk-service",
        service_command(),
        network_config=NETWORK_CONFIG,
        state_dir=env,
        workdir=REPO_ROOT,
    )
    save_state(env / "state.json", state)
    assert task["status"] == "STOPPED"
    assert task["exit_code"] == 0
    log_text = Path(task["log_file"]).read_text(encoding="utf-8")
    assert '"score": 15' in log_text
    assert "usage:" in log_text
    assert "risk-service-task" in log_text
    assert "subnet-0fde9001app" in log_text
    assert state["ecs"]["tasks"][task["task_id"]]["image_digest"].startswith("sha256:")


def test_run_task_denied_when_role_lacks_permissions(env):
    state = load_state(env / "state.json")
    create_role(state, "underpowered")
    ecs.register_task_definition(
        state,
        family="risk-service-broken",
        image_ref="risk-service:v1",
        task_role="underpowered",
        env={},
    )
    with pytest.raises(EcsError) as excinfo:
        ecs.run_task(
            state,
            "risk-service-broken",
            service_command(),
            network_config=NETWORK_CONFIG,
            state_dir=env,
            workdir=REPO_ROOT,
        )
    message = str(excinfo.value)
    assert "AccessDenied" in message
    assert "logs:PutLogEvents" in message
    assert "ecr:BatchGetImage" in message
    assert state["ecs"]["tasks"] == {}


def test_run_task_denied_with_partial_permissions_names_gaps(env):
    state = load_state(env / "state.json")
    put_role_policy(state, "risk-service-task", "pull-only", PULL_ONLY_POLICY)
    underpowered = json.loads(json.dumps(PULL_ONLY_POLICY))
    create_role(state, "pull-only-role")
    put_role_policy(state, "pull-only-role", "pull-only", underpowered)
    ecs.register_task_definition(
        state,
        family="risk-service-pull-only",
        image_ref="risk-service:v1",
        task_role="pull-only-role",
        env={},
    )
    with pytest.raises(EcsError) as excinfo:
        ecs.run_task(
            state,
            "risk-service-pull-only",
            service_command(),
            network_config=NETWORK_CONFIG,
            state_dir=env,
            workdir=REPO_ROOT,
        )
    message = str(excinfo.value)
    assert "AccessDenied" in message
    assert "logs:CreateLogStream" in message
    assert not state["ecs"]["tasks"]


def test_run_task_fails_on_missing_image(env):
    state = load_state(env / "state.json")
    ecs.register_task_definition(
        state,
        family="risk-service",
        image_ref="risk-service:ghost-tag",
        task_role="risk-service-task",
        env={},
    )
    with pytest.raises(EcsError) as excinfo:
        ecs.run_task(
            state,
            "risk-service",
            service_command(),
            network_config=NETWORK_CONFIG,
            state_dir=env,
            workdir=REPO_ROOT,
        )
    assert "not found in registry" in str(excinfo.value)


def test_run_task_fails_on_invalid_network_placement(env):
    broken = json.loads(json.dumps(NETWORK_CONFIG))
    broken["task"]["subnet"] = "subnet-0fde9001public"
    state = load_state(env / "state.json")
    with pytest.raises(EcsError) as excinfo:
        ecs.run_task(
            state,
            "risk-service",
            service_command(),
            network_config=broken,
            state_dir=env,
            workdir=REPO_ROOT,
        )
    assert "network placement" in str(excinfo.value)
    assert state["ecs"]["tasks"] == {}


def test_run_task_fails_on_unknown_task_definition(env):
    state = load_state(env / "state.json")
    with pytest.raises(EcsError) as excinfo:
        ecs.run_task(
            state,
            "ghost-family",
            service_command(),
            network_config=NETWORK_CONFIG,
            state_dir=env,
            workdir=REPO_ROOT,
        )
    assert "no task definition" in str(excinfo.value)


def test_cli_full_ecr_ecs_flow(tmp_path, capsys):
    state_path = tmp_path / "state.json"
    base = ["--state", str(state_path)]
    assert main(["iam", "create-role", "--name", "risk-service-task", *base]) == 0
    assert (
        main(
            [
                "iam",
                "put-role-policy",
                "--role-name",
                "risk-service-task",
                "--policy-name",
                "task-policy",
                "--policy-file",
                str(POLICY_FILE),
                *base,
            ]
        )
        == 0
    )
    assert main(["ecr", "create-repository", "--name", "risk-service", *base]) == 0
    assert (
        main(
            [
                "ecr",
                "push-image",
                "--repository",
                "risk-service",
                "--tag",
                "v1",
                "--source",
                str(REPO_ROOT),
                "--no-docker",
                *base,
            ]
        )
        == 0
    )
    assert "sha256:" in capsys.readouterr().out
    assert (
        main(["ecr", "describe-images", "--repository", "risk-service", *base]) == 0
    )
    assert (
        main(
            [
                "ecs",
                "register-task-definition",
                "--family",
                "risk-service",
                "--image",
                "risk-service:v1",
                "--task-role",
                "risk-service-task",
                "--env",
                "RISKSERVICE_TEST_MARK=1",
                *base,
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "ecs",
                "register-task-definition",
                "--family",
                "risk-service",
                "--image",
                "risk-service:v1",
                "--task-role",
                "risk-service-task",
                "--env",
                "NOVALUE",
                *base,
            ]
        )
        == 1
    )
    assert "invalid --env entry" in capsys.readouterr().out
    exit_code = main(
        [
            "ecs",
            "run-task",
            "--task-definition",
            "risk-service",
            "--network-config",
            str(REPO_ROOT / "deploy" / "network.json"),
            "--workdir",
            str(REPO_ROOT),
            "--state",
            str(state_path),
            "--container-command",
            *service_command(),
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "STOPPED" in out
    task_id = re.search(r"task/risk-service/([0-9a-f]{12})", out).group(1)
    assert main(["ecs", "describe-task", "--task-id", task_id, *base]) == 0
    assert "image_digest" in capsys.readouterr().out
    assert main(["ecs", "describe-task", "--task-id", "nope", *base]) == 1


def test_cli_ecr_push_unknown_repository_fails(tmp_path, capsys):
    exit_code = main(
        [
            "ecr",
            "push-image",
            "--repository",
            "ghost",
            "--tag",
            "v1",
            "--source",
            str(REPO_ROOT),
            "--no-docker",
            "--state",
            str(tmp_path / "state.json"),
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "error:" in out
