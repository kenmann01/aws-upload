"""Tests for the simaws IAM verbs and the least-privilege policy linter.

Seam: the simaws CLI plus its state file. Every test runs offline in tmp_path.
"""

import json
from pathlib import Path

from simaws.cli import main

STATE = "--state"


def args_for(state_path: Path, *rest: str) -> list[str]:
    return [*rest, STATE, str(state_path)]


def write_policy(tmp_path: Path, name: str, document: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


SCOPED_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "PullServiceImage",
            "Effect": "Allow",
            "Action": [
                "ecr:GetAuthorizationToken",
                "ecr:BatchGetImage",
                "ecr:GetDownloadUrlForLayer",
            ],
            "Resource": [
                "arn:simaws:ecr:local:000000000000:repository/risk-service"
            ],
            "justification": "the task must pull its own service image from the one repository it runs from",
        }
    ],
}


def test_create_then_get_role(tmp_path):
    state_path = tmp_path / "state.json"
    assert main(args_for(state_path, "iam", "create-role", "--name", "risk-service-task")) == 0
    assert (
        main(args_for(state_path, "iam", "get-role", "--name", "risk-service-task")) == 0
    )
    out = (state_path.read_text(encoding="utf-8"),)
    state = json.loads(out[0])
    role = state["iam"]["roles"]["risk-service-task"]
    assert role["arn"] == "arn:simaws:iam::000000000000:role/risk-service-task"
    assert role["trust_principal"] == "ecs-tasks.amazonaws.com"


def test_create_duplicate_role_fails(tmp_path, capsys):
    state_path = tmp_path / "state.json"
    assert main(args_for(state_path, "iam", "create-role", "--name", "dup")) == 0
    exit_code = main(args_for(state_path, "iam", "create-role", "--name", "dup"))
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "already exists" in out


def test_get_missing_role_fails(tmp_path, capsys):
    exit_code = main(args_for(tmp_path / "state.json", "iam", "get-role", "--name", "ghost"))
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "not found" in out


def test_put_role_policy_attaches_and_get_role_shows_it(tmp_path, capsys):
    state_path = tmp_path / "state.json"
    policy_file = write_policy(tmp_path, "policy.json", SCOPED_POLICY)
    main(args_for(state_path, "iam", "create-role", "--name", "risk-service-task"))
    assert (
        main(
            args_for(
                state_path,
                "iam",
                "put-role-policy",
                "--role-name",
                "risk-service-task",
                "--policy-name",
                "task-policy",
                "--policy-file",
                str(policy_file),
            )
        )
        == 0
    )
    main(args_for(state_path, "iam", "get-role", "--name", "risk-service-task"))
    out = capsys.readouterr().out
    assert "PullServiceImage" in out
    assert "must pull its own service image" in out


def _rejected_policy_case(tmp_path, capsys, document, fragment) -> None:
    state_path = tmp_path / "state.json"
    policy_file = write_policy(tmp_path, "bad-policy.json", document)
    main(args_for(state_path, "iam", "create-role", "--name", "risk-service-task"))
    exit_code = main(
        args_for(
            state_path,
            "iam",
            "put-role-policy",
            "--role-name",
            "risk-service-task",
            "--policy-name",
            "task-policy",
            "--policy-file",
            str(policy_file),
        )
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert fragment in out
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["iam"]["roles"]["risk-service-task"]["policies"] == {}


def test_policy_with_wildcard_action_rejected(tmp_path, capsys):
    document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "Everything",
                "Effect": "Allow",
                "Action": ["*"],
                "Resource": ["arn:simaws:ecr:local:000000000000:repository/risk-service"],
                "justification": "convenience",
            }
        ],
    }
    _rejected_policy_case(tmp_path, capsys, document, "wildcard")


def test_policy_with_service_wildcard_action_rejected(tmp_path, capsys):
    document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllEcr",
                "Effect": "Allow",
                "Action": ["ecr:*"],
                "Resource": ["arn:simaws:ecr:local:000000000000:repository/risk-service"],
                "justification": "convenience",
            }
        ],
    }
    _rejected_policy_case(tmp_path, capsys, document, "wildcard")


def test_policy_with_wildcard_resource_rejected(tmp_path, capsys):
    document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "Anywhere",
                "Effect": "Allow",
                "Action": ["ecr:BatchGetImage"],
                "Resource": ["*"],
                "justification": "convenience",
            }
        ],
    }
    _rejected_policy_case(tmp_path, capsys, document, "wildcard")


def test_policy_without_justification_rejected(tmp_path, capsys):
    document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "NoReason",
                "Effect": "Allow",
                "Action": ["ecr:BatchGetImage"],
                "Resource": ["arn:simaws:ecr:local:000000000000:repository/risk-service"],
            }
        ],
    }
    _rejected_policy_case(tmp_path, capsys, document, "justification")


def test_policy_with_blank_justification_rejected(tmp_path, capsys):
    document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "BlankReason",
                "Effect": "Allow",
                "Action": ["ecr:BatchGetImage"],
                "Resource": ["arn:simaws:ecr:local:000000000000:repository/risk-service"],
                "justification": "   ",
            }
        ],
    }
    _rejected_policy_case(tmp_path, capsys, document, "justification")


def test_policy_with_deny_statement_rejected(tmp_path, capsys):
    document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "DenyThing",
                "Effect": "Deny",
                "Action": ["ecr:BatchGetImage"],
                "Resource": ["arn:simaws:ecr:local:000000000000:repository/risk-service"],
                "justification": "denials are out of scope for this least-privilege lab",
            }
        ],
    }
    _rejected_policy_case(tmp_path, capsys, document, "Effect")


def test_policy_malformed_json_rejected(tmp_path, capsys):
    state_path = tmp_path / "state.json"
    policy_file = tmp_path / "broken.json"
    policy_file.write_text("{not json", encoding="utf-8")
    main(args_for(state_path, "iam", "create-role", "--name", "risk-service-task"))
    exit_code = main(
        args_for(
            state_path,
            "iam",
            "put-role-policy",
            "--role-name",
            "risk-service-task",
            "--policy-name",
            "task-policy",
            "--policy-file",
            str(policy_file),
        )
    )
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "unusable policy file" in out
