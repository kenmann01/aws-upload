"""Direct unit tests for the least-privilege policy linter.

Seam: validate_policy_document as a pure function. These cover the defensive
shape checks that the CLI-level tests do not reach.
"""

from simaws.iam import validate_policy_document


def valid_statement(**overrides) -> dict:
    statement = {
        "Sid": "Pull",
        "Effect": "Allow",
        "Action": ["ecr:BatchGetImage"],
        "Resource": ["arn:simaws:ecr:local:000000000000:repository/risk-service"],
        "justification": "pull the one image the task runs",
    }
    statement.update(overrides)
    return statement


def test_valid_document_has_no_violations():
    document = {"Version": "2012-10-17", "Statement": [valid_statement()]}
    assert validate_policy_document(document) == []


def test_non_dict_document_rejected():
    assert validate_policy_document(["nope"]) == [
        "policy document must be a JSON object"
    ]


def test_missing_version_rejected():
    document = {"Statement": [valid_statement()]}
    errors = validate_policy_document(document)
    assert any("Version" in error for error in errors)


def test_missing_statement_list_rejected():
    assert any(
        "non-empty list" in error
        for error in validate_policy_document({"Version": "2012-10-17"})
    )
    assert any(
        "non-empty list" in error
        for error in validate_policy_document(
            {"Version": "2012-10-17", "Statement": []}
        )
    )


def test_non_dict_statement_rejected():
    document = {"Version": "2012-10-17", "Statement": ["not an object"]}
    errors = validate_policy_document(document)
    assert any("must be an object" in error for error in errors)


def test_missing_action_list_rejected():
    statement = valid_statement()
    del statement["Action"]
    errors = validate_policy_document(
        {"Version": "2012-10-17", "Statement": [statement]}
    )
    assert any("Action must be a non-empty list" in error for error in errors)


def test_non_string_action_rejected():
    document = {
        "Version": "2012-10-17",
        "Statement": [valid_statement(Action=[42])],
    }
    errors = validate_policy_document(document)
    assert any("Action entries must be strings" in error for error in errors)


def test_action_without_service_prefix_rejected():
    document = {
        "Version": "2012-10-17",
        "Statement": [valid_statement(Action=["BatchGetImage"])],
    }
    errors = validate_policy_document(document)
    assert any("must look like service:Action" in error for error in errors)


def test_missing_resource_list_rejected():
    statement = valid_statement()
    del statement["Resource"]
    errors = validate_policy_document(
        {"Version": "2012-10-17", "Statement": [statement]}
    )
    assert any("Resource must be a non-empty list" in error for error in errors)


def test_non_string_resource_rejected():
    document = {
        "Version": "2012-10-17",
        "Statement": [valid_statement(Resource=[7])],
    }
    errors = validate_policy_document(document)
    assert any("Resource entries must be strings" in error for error in errors)


def test_multiple_violations_reported_together():
    document = {
        "Version": "2012-10-17",
        "Statement": [valid_statement(Action=["*"], Resource=["*"])],
    }
    errors = validate_policy_document(document)
    assert len([e for e in errors if "wildcard" in e]) == 2
