"""Deploy the risk scoring service to the simulated AWS environment, end to end.

    uv run python scripts/deploy_aws_sim.py --backend scripted   (offline)
    uv run python scripts/deploy_aws_sim.py | tee evidence/aws_sim_run.txt

No cloud service is contacted: the entire AWS surface here is the local
simaws control plane, and this script's own output IS the deployment
transcript (validate, IAM, build/push, deploy/run, result). The task role is
the least-privilege role in deploy/iam-policy.json; run-task genuinely
enforces it.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from simaws import ecr, ecs  # noqa: E402
from simaws.ecr import EcrError  # noqa: E402
from simaws.ecs import EcsError  # noqa: E402
from simaws.iam import IamError, create_role, get_role, put_role_policy  # noqa: E402
from simaws.network import (  # noqa: E402
    describe_network,
    load_network_config,
    validate_network,
)
from simaws.state import load_state, save_state  # noqa: E402

ROLE_NAME = "risk-service-task"
POLICY_NAME = "risk-service-task-policy"
REPOSITORY = "risk-service"
IMAGE_TAG = "v1"
FAMILY = "risk-service"

NOTICE = (
    "simulation notice: this deployment runs entirely on the local simaws "
    "control plane; no cloud service is contacted and no cloud account exists"
)


def sha256_file(path: Path) -> str:
    """Content digest of a file, streamed."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    """Run the five deployment phases; the output is the evidence transcript."""
    parser = argparse.ArgumentParser(
        description="Deploy the risk scoring service to the simulated AWS environment."
    )
    parser.add_argument(
        "--backend",
        choices=["ollama", "scripted"],
        default="ollama",
        help="task model backend: live local ollama or deterministic scripted",
    )
    parser.add_argument(
        "--state-dir",
        default=str(REPO_ROOT / ".simaws"),
        help="simaws state directory (state file, image artifacts, task logs)",
    )
    parser.add_argument(
        "--source-dir",
        default=str(REPO_ROOT),
        help="image source directory (the repo checkout)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="model id the task calls (default: RISKSERVICE_MODEL or qwen3:8b, "
        "the managed-endpoint stand-in)",
    )
    args = parser.parse_args(argv)

    state_path = Path(args.state_dir) / "state.json"
    images_dir = Path(args.state_dir) / "images"
    input_path = REPO_ROOT / "deploy" / "input" / "test_input.json"
    network = load_network_config(REPO_ROOT / "deploy" / "network.json")

    print("=== simulated AWS deployment of the risk scoring service ===")
    print(NOTICE)

    print("[1/5] NETWORK validate placement")
    errors = validate_network(network)
    if errors:
        print("  FAIL: placement violates the least-privilege rules:")
        for error in errors:
            print(f"    - {error}")
        return 1
    print("  PASS")
    for line in describe_network(network).splitlines():
        print(f"  {line}")

    print("[2/5] IAM least-privilege task role")
    state = load_state(state_path)
    try:
        role = create_role(state, ROLE_NAME)
        print(f"  created role {role['arn']}")
    except IamError:
        role = get_role(state, ROLE_NAME)
        print(f"  reusing role {role['arn']}")
    policy = json.loads(
        (REPO_ROOT / "deploy" / "iam-policy.json").read_text(encoding="utf-8")
    )
    try:
        put_role_policy(state, ROLE_NAME, POLICY_NAME, policy)
    except IamError as exc:
        print(f"  policy rejected: {exc}")
        return 1
    print(f"  attached policy {POLICY_NAME} (least-privilege linter passed):")
    for statement in policy["Statement"]:
        print(
            f"    {statement['Sid']}: {', '.join(statement['Action'])}"
        )
    save_state(state_path, state)

    print("[3/5] ECR build and push image")
    try:
        try:
            repository = ecr.create_repository(state, REPOSITORY)
            print(f"  created repository {repository['repository_uri']}")
        except EcrError:
            print(f"  reusing repository {REPOSITORY}")
        image = ecr.push_image(
            state,
            REPOSITORY,
            IMAGE_TAG,
            source_dir=Path(args.source_dir),
            images_dir=images_dir,
        )
    except EcrError as exc:
        print(f"  image push failed: {exc}")
        return 1
    save_state(state_path, state)
    print(f"  pushed {REPOSITORY}:{IMAGE_TAG} digest {image['digest']} ({image['packaging']})")

    print("[4/5] ECS register task definition and run task")
    env = {"RISKSERVICE_MODEL": args.model} if args.model else {}
    ecs.register_task_definition(
        state,
        family=FAMILY,
        image_ref=f"{REPOSITORY}:{IMAGE_TAG}",
        task_role=ROLE_NAME,
        env=env,
    )
    command = [
        sys.executable,
        "-m",
        "riskservice",
        "--input",
        str(input_path),
        "--backend",
        args.backend,
    ]
    try:
        task = ecs.run_task(
            state,
            FAMILY,
            command,
            network_config=network,
            state_dir=state_path.parent,
            workdir=args.source_dir,
        )
    except EcsError as exc:
        print(f"  task denied or failed: {exc}")
        return 1
    save_state(state_path, state)
    print(f"  task {task['task_arn']}")
    print(f"  status: {task['status']}  exit code: {task['exit_code']}")

    print("[5/5] RESULT task log")
    print(Path(task["log_file"]).read_text(encoding="utf-8").rstrip())
    print(f"input_sha256: {sha256_file(input_path)}")
    print(NOTICE)
    return 0 if task["exit_code"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
