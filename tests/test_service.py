"""Tests for the riskservice standalone entrypoint.

Seam: the public service function and the CLI, with a scripted model client.
Expected values are worked literals, not recomputations.
"""

import json
from pathlib import Path

import pytest

from riskservice.cli import main
from riskservice.llm import AgentOutputError, ScriptedClient
from riskservice.service import run_risk_service

REPO_ROOT = Path(__file__).resolve().parents[1]
FROZEN_INPUT = REPO_ROOT / "deploy" / "input" / "test_input.json"

# Worked literal reply: factor points 5+5+5 sum exactly to the score.
VALID_SCRIPTED_REPLY = json.dumps(
    {
        "score": 15,
        "factors": [
            {"name": "Credit Band", "points": 5, "detail": "band a"},
            {"name": "No Prior Claims", "points": 5, "detail": "none on file"},
            {"name": "Vehicle Age", "points": 5, "detail": "3 years old"},
        ],
        "rationale": "low risk auto case",
    }
)


def load_frozen_input() -> dict:
    return json.loads(FROZEN_INPUT.read_text(encoding="utf-8"))


def test_run_risk_service_returns_scored_result_with_usage():
    data = load_frozen_input()
    result, usage = run_risk_service(
        data["intake"], data["enrichment"], llm=ScriptedClient({"risk scoring agent": VALID_SCRIPTED_REPLY})
    )
    assert result.score == 15
    assert [f.points for f in result.factors] == [5, 5, 5]
    assert result.rationale == "low risk auto case"
    assert usage["input_tokens"] == 120
    assert usage["output_tokens"] == 80
    assert usage["model"] == "scripted"
    assert usage["duration_ms"] >= 0.0


def test_run_risk_service_rejects_factor_sum_mismatch():
    data = load_frozen_input()
    bad_reply = json.dumps(
        {
            "score": 90,
            "factors": [{"name": "one weak signal", "points": 5, "detail": "d"}],
            "rationale": "unexplained score",
        }
    )
    with pytest.raises(AgentOutputError):
        run_risk_service(
            data["intake"],
            data["enrichment"],
            llm=ScriptedClient({"risk scoring agent": bad_reply}),
        )


def test_cli_scripted_run_exits_zero_with_result_and_usage(capsys):
    exit_code = main(
        ["--input", str(FROZEN_INPUT), "--backend", "scripted"]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert '"score": 15' in out
    assert "input_tokens=120" in out
    assert FROZEN_INPUT.name in out


def test_cli_ollama_unreachable_exits_two(capsys):
    exit_code = main(
        [
            "--input",
            str(FROZEN_INPUT),
            "--backend",
            "ollama",
            "--host",
            "http://127.0.0.1:1",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "http://127.0.0.1:1" in out


def test_cli_unusable_input_file_exits_two(capsys, tmp_path):
    missing = tmp_path / "nope.json"
    exit_code = main(["--input", str(missing), "--backend", "scripted"])
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "unusable input file" in out


def test_cli_invalid_model_reply_exits_one(capsys, monkeypatch):
    import riskservice.cli as cli

    bad_reply = json.dumps(
        {
            "score": 90,
            "factors": [{"name": "one weak signal", "points": 5, "detail": "d"}],
            "rationale": "unexplained score",
        }
    )
    monkeypatch.setattr(cli, "SCRIPTED_RISK_REPLY", bad_reply)
    exit_code = main(["--input", str(FROZEN_INPUT), "--backend", "scripted"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "risk scoring failed" in out
