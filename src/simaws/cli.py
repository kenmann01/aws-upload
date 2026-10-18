"""simaws command line: the verb surface of the simulated control plane.

    simaws iam create-role --name risk-service-task --state .simaws/state.json

Every verb prints human-readable lines (captured as deployment evidence) and
exits 0 on success, 1 on a refused request, 2 on an unusable input file.
"""

import argparse
import json
from pathlib import Path

from simaws import ecr, ecs
from simaws.ecr import EcrError
from simaws.ecs import EcsError
from simaws.iam import IamError, create_role, get_role, put_role_policy
from simaws.network import describe_network, load_network_config, validate_network
from simaws.state import load_state, save_state

DEFAULT_STATE = str(Path(".simaws") / "state.json")


def _add_state_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--state",
        default=DEFAULT_STATE,
        help="path to the account state JSON (default: %(default)s)",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the full verb tree: simaws <service> <verb> [options]."""
    parser = argparse.ArgumentParser(
        prog="simaws",
        description=(
            "Local simulation of the AWS control plane subset used by this "
            "lab (IAM, registry, tasks, network placement). No cloud service "
            "is contacted."
        ),
    )
    services = parser.add_subparsers(dest="service", required=True)

    iam = services.add_parser("iam", help="roles and least-privilege policies")
    iam_verbs = iam.add_subparsers(dest="verb", required=True)
    role = iam_verbs.add_parser("create-role", help="create a role")
    role.add_argument("--name", required=True)
    role.add_argument(
        "--trust-principal", default="ecs-tasks.amazonaws.com"
    )
    _add_state_arg(role)

    attach = iam_verbs.add_parser("put-role-policy", help="attach a policy document")
    attach.add_argument("--role-name", required=True)
    attach.add_argument("--policy-name", required=True)
    attach.add_argument("--policy-file", required=True)
    _add_state_arg(attach)

    show = iam_verbs.add_parser("get-role", help="print a role with its policies")
    show.add_argument("--name", required=True)
    _add_state_arg(show)

    ec2 = services.add_parser("ec2", help="network placement (VPC, subnets, SGs)")
    ec2_verbs = ec2.add_subparsers(dest="verb", required=True)
    validate = ec2_verbs.add_parser(
        "validate-network", help="validate the placement against the least-privilege rules"
    )
    validate.add_argument("--config", required=True)
    describe = ec2_verbs.add_parser(
        "describe-network", help="render the placement for evidence transcripts"
    )
    describe.add_argument("--config", required=True)

    ecr_service = services.add_parser(
        "ecr", help="image registry (create-repository, push-image, describe-images)"
    )
    ecr_verbs = ecr_service.add_subparsers(dest="verb", required=True)
    create_repo = ecr_verbs.add_parser("create-repository", help="create a repository")
    create_repo.add_argument("--name", required=True)
    _add_state_arg(create_repo)

    push = ecr_verbs.add_parser("push-image", help="build and push one image tag")
    push.add_argument("--repository", required=True)
    push.add_argument("--tag", required=True)
    push.add_argument("--source", default=".", help="image source directory")
    push.add_argument(
        "--images-dir", default=None, help="artifact directory (default: state dir /images)"
    )
    docker_mode = push.add_mutually_exclusive_group()
    docker_mode.add_argument(
        "--docker", dest="docker_mode", action="store_true", default=None,
        help="force the docker build path",
    )
    docker_mode.add_argument(
        "--no-docker", dest="docker_mode", action="store_false",
        help="force the source-archive path",
    )
    _add_state_arg(push)

    list_images = ecr_verbs.add_parser(
        "describe-images", help="list a repository's pushed images"
    )
    list_images.add_argument("--repository", required=True)
    _add_state_arg(list_images)

    ecs_service = services.add_parser(
        "ecs", help="task lifecycle (register-task-definition, run-task, describe-task)"
    )
    ecs_verbs = ecs_service.add_subparsers(dest="verb", required=True)
    register = ecs_verbs.add_parser(
        "register-task-definition", help="register (or replace) a family's task definition"
    )
    register.add_argument("--family", required=True)
    register.add_argument("--image", required=True, help="repository:tag")
    register.add_argument("--task-role", required=True)
    register.add_argument(
        "--env", action="append", default=[], metavar="KEY=VALUE",
        help="environment for the task, repeatable",
    )
    _add_state_arg(register)

    run = ecs_verbs.add_parser("run-task", help="authorize and execute one task run")
    run.add_argument("--task-definition", required=True)
    run.add_argument(
        "--network-config", required=True, help="path to the network placement JSON"
    )
    run.add_argument("--workdir", default=".", help="working directory for the task")
    run.add_argument(
        "--container-command",
        nargs=argparse.REMAINDER,
        required=True,
        metavar="ARG",
        help="command the task runs; must be the LAST arguments on the line",
    )
    _add_state_arg(run)

    describe_task = ecs_verbs.add_parser(
        "describe-task", help="print a task's status and log"
    )
    describe_task.add_argument("--task-id", required=True)
    _add_state_arg(describe_task)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Dispatch one simaws verb against the local account state."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.service == "iam":
            return _run_iam(args, Path(args.state))
        if args.service == "ec2":
            return _run_ec2(args)
        if args.service == "ecr":
            return _run_ecr(args)
        if args.service == "ecs":
            return _run_ecs(args)
    except (IamError, EcrError, EcsError) as exc:
        print(f"error: {exc}")
        return 1
    parser.error(f"unknown service {args.service!r}")  # pragma: no cover


def _run_ec2(args: argparse.Namespace) -> int:
    """Run the ec2 verbs (network placement validation and description)."""
    try:
        config = load_network_config(Path(args.config))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"unusable network config {args.config}: {exc}")
        return 2
    if args.verb == "validate-network":
        errors = validate_network(config)
        if errors:
            print("FAIL: network placement violates the least-privilege rules:")
            for error in errors:
                print(f"  - {error}")
            return 1
        print("PASS: network placement satisfies the least-privilege rules")
        print(describe_network(config))
        return 0
    if args.verb == "describe-network":
        print(describe_network(config))
        return 0
    raise AssertionError(f"unhandled ec2 verb {args.verb!r}")  # pragma: no cover


def _state_and_images_dirs(args: argparse.Namespace) -> tuple[Path, Path]:
    """The state file path and its sibling artifacts directory."""
    state_path = Path(args.state)
    images_dir = (
        Path(args.images_dir)
        if getattr(args, "images_dir", None)
        else state_path.parent / "images"
    )
    return state_path, images_dir


def _run_ecr(args: argparse.Namespace) -> int:
    """Run the ecr verbs; every branch returns an exit code."""
    state_path, images_dir = _state_and_images_dirs(args)
    if args.verb == "create-repository":
        state = load_state(state_path)
        repository = ecr.create_repository(state, args.name)
        save_state(state_path, state)
        print(f"repository created: {repository['repository_arn']}")
        print(f"uri: {repository['repository_uri']}")
        return 0
    if args.verb == "push-image":
        state = load_state(state_path)
        image = ecr.push_image(
            state,
            args.repository,
            args.tag,
            source_dir=Path(args.source),
            images_dir=images_dir,
            use_docker=args.docker_mode,
        )
        save_state(state_path, state)
        print(f"pushed {args.repository}:{args.tag} ({image['packaging']})")
        print(f"digest: {image['digest']}")
        print(f"artifact: {image['artifact']} ({image['size_bytes']} bytes)")
        return 0
    if args.verb == "describe-images":
        state = load_state(state_path)
        print(ecr.describe_images(state, args.repository))
        return 0
    raise AssertionError(f"unhandled ecr verb {args.verb!r}")  # pragma: no cover


def _parse_env_pairs(pairs: list[str]) -> dict[str, str]:
    """Parse KEY=VALUE repeatable env arguments."""
    env: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise EcsError(f"invalid --env entry {pair!r}; expected KEY=VALUE")
        env[key] = value
    return env


def _run_ecs(args: argparse.Namespace) -> int:
    """Run the ecs verbs; every branch returns an exit code."""
    state_path = Path(args.state)
    if args.verb == "register-task-definition":
        state = load_state(state_path)
        definition = ecs.register_task_definition(
            state,
            family=args.family,
            image_ref=args.image,
            task_role=args.task_role,
            env=_parse_env_pairs(args.env),
        )
        save_state(state_path, state)
        print(f"task definition registered: {definition['family']}")
        print(f"image: {definition['image']}  role: {definition['task_role']}")
        for key, value in definition["env"].items():
            print(f"env: {key}={value}")
        return 0
    if args.verb == "run-task":
        state = load_state(state_path)
        network_config = load_network_config(Path(args.network_config))
        task = ecs.run_task(
            state,
            args.task_definition,
            args.container_command,
            network_config=network_config,
            state_dir=state_path.parent,
            workdir=Path(args.workdir),
        )
        save_state(state_path, state)
        print(f"task started: {task['task_arn']}")
        print(f"status: {task['status']}  exit code: {task['exit_code']}")
        print(f"log: {task['log_file']}")
        print("--- task log ---")
        print(Path(task["log_file"]).read_text(encoding="utf-8").rstrip())
        return 0 if task["exit_code"] == 0 else 1
    if args.verb == "describe-task":
        state = load_state(state_path)
        task = ecs.get_task(state, args.task_id)
        print(json.dumps(task, indent=2))
        print("--- task log ---")
        print(Path(task["log_file"]).read_text(encoding="utf-8").rstrip())
        return 0
    raise AssertionError(f"unhandled ecs verb {args.verb!r}")  # pragma: no cover


def _run_iam(args: argparse.Namespace, state_path: Path) -> int:
    """Run the iam verbs; args.service == 'iam' guaranteed by the parser.

    _run_iam expects to be dispatched with the parsed state path; every iam
    verb carries --state.
    """
    if args.verb == "create-role":
        state = load_state(state_path)
        role = create_role(state, args.name, args.trust_principal)
        save_state(state_path, state)
        print(f"role created: {role['arn']}")
        print(f"trust: {role['trust_principal']}")
        return 0
    if args.verb == "put-role-policy":
        return _run_put_role_policy(args, state_path)
    if args.verb == "get-role":
        state = load_state(state_path)
        role = get_role(state, args.name)
        print(json.dumps(role, indent=2))
        return 0
    raise AssertionError(f"unhandled iam verb {args.verb!r}")  # pragma: no cover


def _run_put_role_policy(args: argparse.Namespace, state_path: Path) -> int:
    """Validate the policy file, then attach it; 2 on an unusable file."""
    try:
        document = json.loads(Path(args.policy_file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"unusable policy file {args.policy_file}: {exc}")
        return 2
    state = load_state(state_path)
    put_role_policy(state, args.role_name, args.policy_name, document)
    save_state(state_path, state)
    print(f"policy attached: {args.policy_name} -> role {args.role_name}")
    for statement in document["Statement"]:
        sid = statement.get("Sid", "")
        print(f"  {sid}: {', '.join(statement['Action'])}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
