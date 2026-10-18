"""Command line entrypoint for the risk scoring service.

    python -m riskservice --input deploy/input/test_input.json --backend scripted
"""

import argparse
import json
import sys
from pathlib import Path

from riskservice.llm import AgentOutputError, OllamaClient, ScriptedClient
from riskservice.service import run_risk_service

# Offline demo reply whose factor points (5+5+5) sum exactly to the score, so
# the scripted backend exercises the same validation path as a live model.
SCRIPTED_RISK_REPLY = json.dumps(
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


def main(argv: list[str] | None = None) -> int:
    """Run one scoring pass and print the result and usage.

    Returns 0 on success, 1 when the model reply is invalid, and 2 when the
    input file is unusable or the ollama backend is unreachable.
    """
    parser = argparse.ArgumentParser(
        prog="riskservice",
        description="Score one underwriting case with the risk scoring agent.",
    )
    parser.add_argument(
        "--input",
        required=True,
        help="path to the input JSON with intake and enrichment objects",
    )
    parser.add_argument(
        "--backend",
        choices=["ollama", "scripted"],
        default="ollama",
        help="ollama calls the local model server, scripted is deterministic offline",
    )
    parser.add_argument("--model", default=None, help="model id for the ollama backend")
    parser.add_argument("--host", default=None, help="base URL for the ollama backend")
    args = parser.parse_args(argv)

    try:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        intake_data = payload["intake"]
        enrichment_data = payload["enrichment"]
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"unusable input file {args.input}: {exc}")
        return 2

    if args.backend == "scripted":
        client = ScriptedClient({"risk scoring agent": SCRIPTED_RISK_REPLY})
    else:
        client = OllamaClient(host=args.host, model=args.model)
        if not client.health():
            print(
                f"model endpoint is not reachable at {client.host}. "
                "Start the model server and pull the model, or pass "
                "--backend scripted for an offline run."
            )
            return 2

    try:
        result, usage = run_risk_service(intake_data, enrichment_data, llm=client)
    except AgentOutputError as exc:
        print(f"risk scoring failed: {exc}")
        return 1

    print(f"input: {Path(args.input).name}")
    print(json.dumps(result.model_dump(), indent=2))
    print(
        f"usage: model={usage['model']} input_tokens={usage['input_tokens']} "
        f"output_tokens={usage['output_tokens']} duration_ms={usage['duration_ms']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
