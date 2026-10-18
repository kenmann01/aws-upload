"""Additional ecr branch tests: duplicates, empty listings, docker path."""

import hashlib
from pathlib import Path

import pytest

from simaws import ecr
from simaws.ecr import EcrError
from simaws.state import empty_state

REPO_ROOT = Path(__file__).resolve().parents[1]


class _FakeResult:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


def test_create_duplicate_repository_rejected():
    state = empty_state()
    ecr.create_repository(state, "risk-service")
    with pytest.raises(EcrError):
        ecr.create_repository(state, "risk-service")


def test_describe_images_empty_repository():
    state = empty_state()
    ecr.create_repository(state, "risk-service")
    text = ecr.describe_images(state, "risk-service")
    assert "no images pushed" in text


def _fake_docker_runner(save_writes_artifact: bool, build_code: int = 0, save_code: int = 0):
    calls: list[list[str]] = []

    def runner(command: list[str], check: bool) -> _FakeResult:
        calls.append(command)
        if command[1] == "save" and save_writes_artifact:
            artifact = Path(command[command.index("-o") + 1])
            artifact.write_bytes(b"image-bytes")
        return _FakeResult(build_code if command[1] == "build" else save_code)

    return runner, calls


def test_push_image_docker_path_records_digest(tmp_path):
    state = empty_state()
    ecr.create_repository(state, "risk-service")
    runner, calls = _fake_docker_runner(save_writes_artifact=True)
    image = ecr.push_image(
        state,
        "risk-service",
        "v1",
        source_dir=REPO_ROOT,
        images_dir=tmp_path / "images",
        use_docker=True,
        runner=runner,
    )
    assert image["packaging"] == "docker"
    assert (
        image["digest"]
        == "sha256:" + hashlib.sha256(b"image-bytes").hexdigest()
    )
    assert image["size_bytes"] == len(b"image-bytes")
    assert [call[1] for call in calls] == ["build", "save"]


def test_push_image_docker_build_failure_rejected(tmp_path):
    state = empty_state()
    ecr.create_repository(state, "risk-service")
    runner, _ = _fake_docker_runner(save_writes_artifact=False, build_code=1)
    with pytest.raises(EcrError, match="docker build failed"):
        ecr.push_image(
            state,
            "risk-service",
            "v1",
            source_dir=REPO_ROOT,
            images_dir=tmp_path / "images",
            use_docker=True,
            runner=runner,
        )


def test_push_image_docker_save_failure_rejected(tmp_path):
    state = empty_state()
    ecr.create_repository(state, "risk-service")
    runner, _ = _fake_docker_runner(save_writes_artifact=False, save_code=1)
    with pytest.raises(EcrError, match="docker save failed"):
        ecr.push_image(
            state,
            "risk-service",
            "v1",
            source_dir=REPO_ROOT,
            images_dir=tmp_path / "images",
            use_docker=True,
            runner=runner,
        )


def test_sha256_file_streams_content(tmp_path):
    artifact = tmp_path / "blob.bin"
    artifact.write_bytes(b"stream me")
    import hashlib

    assert ecr._sha256_file(artifact) == hashlib.sha256(b"stream me").hexdigest()
