"""Simulated network placement and the validator that keeps it honest.

The config describes a VPC, its subnets, security groups, and where the task
is placed. The validator enforces the lab's networking story: the task sits in
a private subnet, accepts no world-open ingress, and may egress only to the
model endpoint. This is a simulated placement document; no cloud account
exists.
"""

import json
from pathlib import Path


def validate_network(config: object) -> list[str]:
    """Return the list of placement violations; an empty list means PASS."""
    errors: list[str] = []
    if not isinstance(config, dict):
        return ["network config must be a JSON object"]
    vpc = config.get("vpc")
    if not isinstance(vpc, dict) or "id" not in vpc or "cidr" not in vpc:
        errors.append("vpc must be an object with id and cidr")
    subnets_by_id = _index_named(config.get("subnets"), "subnets", errors)
    groups_by_id = _index_named(
        config.get("security_groups"), "security_groups", errors
    )
    task = config.get("task")
    if not isinstance(task, dict):
        errors.append(
            "task placement (subnet, security_group, model_endpoint) is required"
        )
        return errors
    subnet_id = task.get("subnet")
    subnet = subnets_by_id.get(subnet_id)
    if subnet is None:
        errors.append(f"unknown subnet '{subnet_id}' for task placement")
    elif subnet.get("public") is not False:
        errors.append(
            f"task subnet '{subnet_id}' must be a private subnet; public subnets "
            "expose the task to direct internet reachability"
        )
    group_id = task.get("security_group")
    group = groups_by_id.get(group_id)
    if group is None:
        errors.append(f"unknown security group '{group_id}' for task placement")
    else:
        errors.extend(_check_ingress(group_id, group))
        errors.extend(_check_egress(group_id, group, task))
    return errors


def _index_named(entries: object, label: str, errors: list[str]) -> dict:
    """Index a list of {id, ...} objects by id, reporting shape problems."""
    if not isinstance(entries, list) or not entries:
        errors.append(f"{label} must be a non-empty list")
        return {}
    indexed: dict = {}
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            indexed[entry["id"]] = entry
        else:
            errors.append(f"every entry in {label} must be an object with an id")
    return indexed


def _check_ingress(group_id: str, group: dict) -> list[str]:
    """No world-open ingress; any ingress rule at all needs a justification."""
    errors: list[str] = []
    rules = group.get("ingress")
    if rules is None:
        return errors
    if not isinstance(rules, list):
        return [f"{group_id} ingress must be a list"]
    for rule in rules:
        if not isinstance(rule, dict):
            errors.append(f"{group_id} ingress rules must be objects")
            continue
        if rule.get("cidr") == "0.0.0.0/0":
            errors.append(
                f"{group_id} has world-open ingress (0.0.0.0/0); the risk "
                "service accepts no inbound traffic"
            )
        justification = rule.get("justification")
        if not isinstance(justification, str) or not justification.strip():
            errors.append(
                f"every ingress rule on {group_id} needs a non-empty justification"
            )
    return errors


def _check_egress(group_id: str, group: dict, task: dict) -> list[str]:
    """Egress must contain exactly the model endpoint rule and nothing else."""
    endpoint = task.get("model_endpoint")
    if not isinstance(endpoint, dict) or "cidr" not in endpoint or "port" not in endpoint:
        return [
            f"task.model_endpoint (cidr, port) is required to check {group_id} egress"
        ]
    errors: list[str] = []
    rules = group.get("egress")
    if not isinstance(rules, list) or not rules:
        return [
            f"{group_id} must define egress for the model endpoint "
            f"({endpoint['cidr']}:{endpoint['port']})"
        ]
    matched = False
    for rule in rules:
        if not isinstance(rule, dict):
            errors.append(f"{group_id} egress rules must be objects")
            continue
        justification = rule.get("justification")
        if not isinstance(justification, str) or not justification.strip():
            errors.append(
                f"every egress rule on {group_id} needs a non-empty justification"
            )
        if (
            rule.get("protocol") == "tcp"
            and rule.get("port") == endpoint["port"]
            and rule.get("cidr") == endpoint["cidr"]
        ):
            matched = True
        else:
            errors.append(
                f"egress on {group_id} must be limited to the model endpoint "
                f"({endpoint['cidr']}:{endpoint['port']}); this rule allows "
                f"{rule.get('cidr')}:{rule.get('port')}"
            )
    if not matched:
        errors.append(
            f"{group_id} has no egress rule for the model endpoint "
            f"({endpoint['cidr']}:{endpoint['port']})"
        )
    return errors


def describe_network(config: dict) -> str:
    """Render the placement as human-readable lines for the evidence transcript."""
    lines: list[str] = []
    vpc = config.get("vpc", {})
    lines.append(f"vpc {vpc.get('id')} ({vpc.get('cidr')})")
    task = config.get("task", {})
    task_subnet = task.get("subnet")
    lines.append("subnets:")
    for subnet in config.get("subnets", []):
        marker = "  <- task placement" if subnet.get("id") == task_subnet else ""
        visibility = "PUBLIC" if subnet.get("public") else "private"
        lines.append(
            f"  {subnet.get('id')}  {subnet.get('cidr')}  {visibility}{marker}"
        )
    lines.append("security groups:")
    for group in config.get("security_groups", []):
        lines.append(f"  {group.get('id')}  {group.get('description', '')}")
        ingress = group.get("ingress", [])
        if ingress:
            for rule in ingress:
                lines.append(
                    f"    ingress {rule.get('protocol')} {rule.get('port')} from {rule.get('cidr')}"
                )
        else:
            lines.append("    ingress: none (the service accepts no inbound traffic)")
        for rule in group.get("egress", []):
            lines.append(
                f"    egress {rule.get('protocol')} {rule.get('port')} to {rule.get('cidr')}"
            )
            lines.append(f"      why: {rule.get('justification')}")
    endpoint = task.get("model_endpoint", {})
    lines.append(
        f"model endpoint: {endpoint.get('cidr')}:{endpoint.get('port')} "
        "(simulated managed model service)"
    )
    return "\n".join(lines)


def load_network_config(path: Path) -> object:
    """Read a network config JSON file; raises OSError/JSONDecodeError."""
    return json.loads(Path(path).read_text(encoding="utf-8"))
