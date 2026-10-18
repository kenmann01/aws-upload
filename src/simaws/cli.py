"""simaws command line: the verb surface of the simulated control plane.

    simaws iam create-role --name risk-service-task --state .simaws/state.json

Every verb prints human-readable lines (captured as deployment evidence) and
exits 0 on success, 1 on a refused request, 2 on an unusable input file.
"""

import argparse
import json
from pathlib import Path

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
    except IamError as exc:
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
