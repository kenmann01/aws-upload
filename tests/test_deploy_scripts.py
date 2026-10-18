"""End-to-end tests for the two deploy scripts (subprocess level).

Both scripts must run offline on the scripted backend, be idempotent, print
the frozen input's sha256 (the same-test-input evidence), and refuse clearly
when a live model endpoint is unreachable.
"""

import hashlib
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AWS_SCRIPT = REPO_ROOT / "scripts" / "deploy_aws_sim.py"
ONPREM_SCRIPT = REPO_ROOT / "scripts" / "deploy_onprem.py"
FROZEN_INPUT = REPO_ROOT / "deploy" / "input" / "test_input.json"

EXPECTED_INPUT_SHA = hashlib.sha256(FROZEN_INPUT.read_bytes()).hexdigest()

PHASES = ["[1/5] NETWORK", "[2/5] IAM", "[3/5] ECR", "[4/5] ECS", "[5/5] RESULT"]


def run_aws(tmp_path: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(AWS_SCRIPT),
            "--backend",
            "scripted",
            "--state-dir",
            str(tmp_path / ".simaws"),
            *extra,
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=300,
    )


def test_deploy_aws_sim_scripted_end_to_end(tmp_path):
    result = run_aws(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    for phase in PHASES:
        assert phase in out
    assert "PASS" in out
    assert "sha256:" in out
    assert '"score": 15' in out
    assert f"input_sha256: {EXPECTED_INPUT_SHA}" in out
    assert "no cloud service" in out


def test_deploy_aws_sim_is_idempotent(tmp_path):
    first = run_aws(tmp_path)
    assert first.returncode == 0, first.stdout + first.stderr
    second = run_aws(tmp_path)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "reusing" in second.stdout
    assert f"input_sha256: {EXPECTED_INPUT_SHA}" in second.stdout


def run_onprem(*extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ONPREM_SCRIPT), *extra],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=300,
    )


def test_deploy_onprem_scripted_end_to_end(tmp_path):
    result = run_onprem("--backend", "scripted")
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    assert "on-prem" in out
    assert '"score": 15' in out
    assert f"input_sha256: {EXPECTED_INPUT_SHA}" in out
    assert "no cloud service" in out


def test_deploy_onprem_defaults_to_smaller_open_weight_model(tmp_path):
    result = run_onprem("--backend", "scripted")
    assert "qwen3:4b" in result.stdout


def test_both_scripts_run_the_same_frozen_input(tmp_path):
    aws = run_aws(tmp_path)
    onprem = run_onprem("--backend", "scripted")
    assert aws.returncode == 0 and onprem.returncode == 0
    aws_hash = next(
        line for line in aws.stdout.splitlines() if line.startswith("input_sha256:")
    )
    onprem_hash = next(
        line for line in onprem.stdout.splitlines() if line.startswith("input_sha256:")
    )
    assert aws_hash == onprem_hash


def test_deploy_onprem_unreachable_host_exits_two():
    result = run_onprem("--backend", "ollama", "--host", "http://127.0.0.1:1")
    assert result.returncode == 2
    assert "not reachable" in result.stdout
    assert "http://127.0.0.1:1" in result.stdout
