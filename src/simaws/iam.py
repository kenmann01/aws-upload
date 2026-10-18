"""Simulated IAM: roles, policies, and a least-privilege linter.

The linter is deliberately stricter than real IAM: every statement must be an
Allow with non-wildcard actions and non-wildcard resources, and must carry a
non-empty justification string. The justification field is this simulator's
non-standard addition to the policy document; it exists so the lab's "clear
justification for each permission" criterion is enforced by code instead of
asserted in prose.
"""

import re

from simaws.state import ACCOUNT_ID, PARTITION

class IamError(RuntimeError):
    """Raised when an IAM verb cannot do what was asked."""

# service:Action with no wildcard characters anywhere.
_ACTION_RE = re.compile(r"^[a-z0-9][a-z0-9-]*:[A-Za-z0-9]+$")


def role_arn(name: str) -> str:
    """The simulated ARN for a role."""
    return f"arn:{PARTITION}:iam::{ACCOUNT_ID}:role/{name}"


def create_role(
    state: dict, name: str, trust_principal: str = "ecs-tasks.amazonaws.com"
) -> dict:
    """Create a role assumable by the given principal; refuse duplicates."""
    roles = state["iam"]["roles"]
    if name in roles:
        raise IamError(f"role '{name}' already exists")
    role = {
        "role_name": name,
        "arn": role_arn(name),
        "trust_principal": trust_principal,
        "policies": {},
    }
    roles[name] = role
    return role


def get_role(state: dict, name: str) -> dict:
    """Return the role document; raise when it does not exist."""
    role = state["iam"]["roles"].get(name)
    if role is None:
        raise IamError(f"role '{name}' not found")
    return role


def validate_policy_document(document: object) -> list[str]:
    """Return the list of least-privilege violations in a policy document.

    An empty list means the document is attachable. Every check exists to keep
    the simulator unable to express an over-broad grant.
    """
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["policy document must be a JSON object"]
    if not isinstance(document.get("Version"), str):
        errors.append("policy document is missing a Version string")
    statements = document.get("Statement")
    if not isinstance(statements, list) or not statements:
        errors.append("Statement must be a non-empty list")
        return errors
    for index, statement in enumerate(statements):
        prefix = f"Statement[{index}]"
        if not isinstance(statement, dict):
            errors.append(f"{prefix} must be an object")
            continue
        if statement.get("Effect") != "Allow":
            errors.append(
                f"{prefix}: Effect must be 'Allow'; this linter only accepts least-privilege Allow statements"
            )
        errors.extend(_check_actions(prefix, statement.get("Action")))
        errors.extend(_check_resources(prefix, statement.get("Resource")))
        justification = statement.get("justification")
        if not isinstance(justification, str) or not justification.strip():
            errors.append(
                f"{prefix}: a non-empty 'justification' string is required for every statement"
            )
    return errors


def _check_actions(prefix: str, actions: object) -> list[str]:
    """Reject missing, non-string, or wildcarded action lists."""
    if not isinstance(actions, list) or not actions:
        return [f"{prefix}: Action must be a non-empty list of strings"]
    errors: list[str] = []
    for action in actions:
        if not isinstance(action, str):
            errors.append(f"{prefix}: Action entries must be strings")
        elif "*" in action:
            errors.append(
                f"{prefix}: wildcard action '{action}' rejected (least privilege)"
            )
        elif not _ACTION_RE.match(action):
            errors.append(f"{prefix}: action '{action}' must look like service:Action")
    return errors


def _check_resources(prefix: str, resources: object) -> list[str]:
    """Reject missing, non-string, or wildcarded resource lists."""
    if not isinstance(resources, list) or not resources:
        return [f"{prefix}: Resource must be a non-empty list of strings"]
    errors: list[str] = []
    for resource in resources:
        if not isinstance(resource, str):
            errors.append(f"{prefix}: Resource entries must be strings")
        elif "*" in resource or "?" in resource:
            errors.append(
                f"{prefix}: wildcard resource '{resource}' rejected (least privilege)"
            )
    return errors


def put_role_policy(
    state: dict, role_name: str, policy_name: str, document: object
) -> dict:
    """Validate and attach an inline policy to a role.

    Raises IamError listing every linter violation when the document is not
    attachable; state is untouched in that case.
    """
    role = get_role(state, role_name)
    errors = validate_policy_document(document)
    if errors:
        raise IamError("; ".join(errors))
    role["policies"][policy_name] = document
    return document
