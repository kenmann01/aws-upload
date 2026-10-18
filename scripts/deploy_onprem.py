"""Run the risk scoring service against the simulated on-prem deployment.

    uv run python scripts/deploy_onprem.py --backend scripted   (offline)
    uv run python scripts/deploy_onprem.py | tee evidence/onprem_run.txt

On-prem here means the model runs inside the boundary: a local Ollama server
hosting a small open-weight model, no external API anywhere. This is the
course's development-stage stand-in for a client's private hosting stack
(the Week 9 articles name vLLM as the production-stage tool); the service
code and the frozen test input are exactly the ones the AWS-style deployment
runs, so the comparison section compares like with like.
"""

import argparse
import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from riskservice.cli import main as service_main  # noqa: E402
from riskservice.llm import OllamaClient  # noqa: E402

DEFAULT_ONPREM_MODEL = "qwen3:4b"

NOTICE = (
    "simulation notice: this on-prem run executes on this machine with a "
    "local model server; no cloud service is contacted and no external "
    "model API is called"
)


def sha256_file(path: Path) -> str:
    """Content digest of a file, streamed."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    """Health-check the boundary's model host, then run the service."""
    parser = argparse.ArgumentParser(
        description="Run the risk scoring service in the simulated on-prem deployment."
    )
    parser.add_argument(
        "--backend",
        choices=["ollama", "scripted"],
        default="ollama",
        help="live local ollama or deterministic scripted (offline verification)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="on-prem model id (default: ONPREM_MODEL or qwen3:4b)",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="model host (default: RISKSERVICE_OLLAMA_HOST, OLLAMA_HOST, or "
        "http://127.0.0.1:11434)",
    )
    parser.add_argument(
        "--input",
        default=str(REPO_ROOT / "deploy" / "input" / "test_input.json"),
        help="frozen test input; the SAME file the AWS-style deployment runs",
    )
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    model = args.model or DEFAULT_ONPREM_MODEL

    print("=== simulated on-prem deployment of the risk scoring service ===")
    print(f"boundary: this machine | model host: {args.host or 'local default'} | model: {model}")
    print(NOTICE)

    if args.backend == "ollama":
        client = OllamaClient(host=args.host, model=model)
        if not client.health():
            print(
                f"the on-prem model endpoint is not reachable at {client.host}. "
                "Start the model server inside the boundary and pull the model, "
                "or pass --backend scripted for an offline verification run."
            )
            return 2

    exit_code = service_main(
        [
            "--input",
            str(input_path),
            "--backend",
            args.backend,
            "--model",
            model,
            *(["--host", args.host] if args.host else []),
        ]
    )
    print(f"input_sha256: {sha256_file(input_path)}")
    print(NOTICE)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
