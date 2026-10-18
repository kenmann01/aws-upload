"""Tests for the simaws network placement validator.

Seams: validate_network as a pure function, plus its CLI verbs. The committed
deploy/network.json is the real artifact and must pass.
"""

import copy
import json
from pathlib import Path

from simaws.cli import main
from simaws.network import describe_network, validate_network

REPO_ROOT = Path(__file__).resolve().parents[1]
NETWORK_CONFIG = REPO_ROOT / "deploy" / "network.json"


def load_config() -> dict:
    return json.loads(NETWORK_CONFIG.read_text(encoding="utf-8"))


def test_committed_placement_passes_validation():
    assert validate_network(load_config()) == []


def _invalid(mutate) -> dict:
    config = load_config()
    mutate(config)
    return config


def test_public_subnet_placement_rejected():
    def put_task_on_public(config):
        config["task"]["subnet"] = "subnet-0fde9001public"

    errors = validate_network(_invalid(put_task_on_public))
    assert any("private" in error for error in errors)


def test_world_open_ingress_rejected():
    def open_ingress(config):
        config["security_groups"][0]["ingress"].append(
            {"protocol": "tcp", "port": 8080, "cidr": "0.0.0.0/0", "justification": "x"}
        )

    errors = validate_network(_invalid(open_ingress))
    assert any("world-open" in error for error in errors)


def test_ingress_rule_without_justification_rejected():
    def unjustified(config):
        config["security_groups"][0]["ingress"].append(
            {"protocol": "tcp", "port": 8080, "cidr": "10.9.0.0/24"}
        )

    errors = validate_network(_invalid(unjustified))
    assert any("justification" in error for error in errors)


def test_missing_model_endpoint_egress_rejected():
    def drop_egress(config):
        config["security_groups"][0]["egress"] = []

    errors = validate_network(_invalid(drop_egress))
    assert any("model endpoint" in error for error in errors)


def test_wrong_port_or_cidr_for_model_endpoint_rejected():
    def wrong_port(config):
        config["security_groups"][0]["egress"][0]["port"] = 9999

    errors = validate_network(_invalid(wrong_port))
    assert any("model endpoint" in error for error in errors)

    def wrong_cidr(config):
        config["security_groups"][0]["egress"][0]["cidr"] = "10.9.9.0/24"

    errors = validate_network(_invalid(wrong_cidr))
    assert any("model endpoint" in error for error in errors)


def test_extra_egress_rule_rejected():
    def extra_rule(config):
        config["security_groups"][0]["egress"].append(
            {
                "protocol": "tcp",
                "port": 443,
                "cidr": "0.0.0.0/0",
                "justification": "general internet access",
            }
        )

    errors = validate_network(_invalid(extra_rule))
    assert any("model endpoint" in error for error in errors)


def test_egress_rule_without_justification_rejected():
    def unjustified(config):
        config["security_groups"][0]["egress"][0].pop("justification")

    errors = validate_network(_invalid(unjustified))
    assert any("justification" in error for error in errors)


def test_unknown_task_subnet_rejected():
    def ghost_subnet(config):
        config["task"]["subnet"] = "subnet-ghost"

    errors = validate_network(_invalid(ghost_subnet))
    assert any("unknown subnet" in error for error in errors)


def test_unknown_security_group_rejected():
    def ghost_sg(config):
        config["task"]["security_group"] = "sg-ghost"

    errors = validate_network(_invalid(ghost_sg))
    assert any("unknown security group" in error for error in errors)


def test_malformed_config_rejected():
    errors = validate_network({"vpc": {}})
    assert len(errors) >= 1
    assert any("task" in error for error in errors)


def test_non_dict_config_rejected():
    assert validate_network(["nope"]) == ["network config must be a JSON object"]


def test_non_object_subnet_and_group_entries_rejected():
    errors = validate_network(
        {
            "vpc": {"id": "v", "cidr": "10.9.0.0/16"},
            "subnets": ["not-an-object"],
            "security_groups": [42],
            "task": {
                "subnet": "s",
                "security_group": "g",
                "model_endpoint": {"cidr": "10.9.2.0/24", "port": 11434},
            },
        }
    )
    assert any("every entry in subnets" in error for error in errors)
    assert any("every entry in security_groups" in error for error in errors)
    assert any("unknown subnet" in error for error in errors)


def test_missing_model_endpoint_rejected():
    def drop_endpoint(config):
        config["task"].pop("model_endpoint")

    errors = validate_network(_invalid(drop_endpoint))
    assert any("task.model_endpoint" in error for error in errors)


def test_ingress_key_absent_passes():
    def drop_ingress(config):
        config["security_groups"][0].pop("ingress")

    assert validate_network(_invalid(drop_ingress)) == []


def test_ingress_not_a_list_rejected():
    def bad_ingress(config):
        config["security_groups"][0]["ingress"] = "nope"

    errors = validate_network(_invalid(bad_ingress))
    assert any("ingress must be a list" in error for error in errors)


def test_non_object_ingress_rule_rejected():
    def bad_rule(config):
        config["security_groups"][0]["ingress"] = ["nope"]

    errors = validate_network(_invalid(bad_rule))
    assert any("ingress rules must be objects" in error for error in errors)


def test_non_object_egress_rule_rejected():
    def bad_rule(config):
        config["security_groups"][0]["egress"] = ["nope"]

    errors = validate_network(_invalid(bad_rule))
    assert any("egress rules must be objects" in error for error in errors)


def test_describe_network_renders_ingress_rules():
    config = load_config()
    config["security_groups"][0]["ingress"] = [
        {
            "protocol": "tcp",
            "port": 8080,
            "cidr": "10.9.0.0/24",
            "justification": "metrics scrape from the internal subnet",
        }
    ]
    text = describe_network(config)
    assert "ingress tcp 8080 from 10.9.0.0/24" in text


def test_describe_network_renders_placement():
    text = describe_network(load_config())
    assert "subnet-0fde9001app" in text
    assert "private" in text
    assert "11434" in text


def test_cli_validate_pass_and_fail(tmp_path, capsys):
    assert main(["ec2", "validate-network", "--config", str(NETWORK_CONFIG)]) == 0
    assert "PASS" in capsys.readouterr().out

    broken = _invalid(lambda c: c["task"].__setitem__("subnet", "subnet-ghost"))
    path = tmp_path / "broken-network.json"
    path.write_text(json.dumps(broken), encoding="utf-8")
    exit_code = main(["ec2", "validate-network", "--config", str(path)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "FAIL" in out
    assert "unknown subnet" in out


def test_cli_describe_network(tmp_path, capsys):
    exit_code = main(["ec2", "describe-network", "--config", str(NETWORK_CONFIG)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "vpc-0fde9001" in out


def test_cli_unusable_config_file(tmp_path, capsys):
    missing = tmp_path / "nope.json"
    exit_code = main(["ec2", "validate-network", "--config", str(missing)])
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "unusable network config" in out
