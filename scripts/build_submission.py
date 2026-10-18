"""Build the submission PDF for the Week 9 lab.

Assembles the eight deliverable exhibits (in the brief's order) into one
print-styled HTML file at the repo root, then prints it to submission.pdf
with headless Edge or Chromium. Missing run-day evidence renders as amber
PENDING boxes naming the producing command; deploy/ and docs/ and src/ inputs
are committed artifacts and fail loudly when absent.

    uv run python scripts/build_submission.py
"""

import ast
import html
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

KEYWORDS = {
    "def", "class", "return", "if", "elif", "else", "for", "while", "in", "not",
    "and", "or", "import", "from", "as", "with", "async", "await", "try", "except",
    "raise", "None", "True", "False", "self", "yield", "lambda", "pass", "break",
    "continue", "is", "assert", "finally", "del",
}

AWS_RUN = "evidence/aws_sim_run.txt"
ONPREM_RUN = "evidence/onprem_run.txt"
OLLAMA_SETUP = "evidence/ollama_setup.txt"
IAM_ROLE = "evidence/iam_role.txt"


def read(rel: str) -> str:
    """Read a repo-relative mandatory file and drop trailing whitespace.

    A missing docs/, deploy/, or src/ input raises OSError here on purpose:
    the build fails loudly instead of shipping a page with a hole in it.
    """
    return (ROOT / rel).read_text(encoding="utf-8").rstrip()


def highlight_python(code: str) -> str:
    """Wrap Python keywords, strings, and comments in highlight spans."""
    out = []
    for line in code.splitlines():
        escaped = html.escape(line, quote=False)
        parts = re.split(r"(#.*$)", escaped, maxsplit=1)
        tokens = []
        for i, part in enumerate(parts):
            if i == 1:
                tokens.append(f'<span class="c">{part}</span>')
                continue
            part = re.sub(r'(".*?"|\'.*?\')', r'<span class="s">\1</span>', part)
            for kw in KEYWORDS:
                part = re.sub(rf"\b({kw})\b(?![^<]*</span>)", r'<span class="k">\1</span>', part)
            tokens.append(part)
        out.append("".join(tokens))
    return "\n".join(out)


def code_block(source: str) -> str:
    """Render Python source as a highlighted code block."""
    return f'<pre class="code">{highlight_python(source)}</pre>'


def plain_block(source: str) -> str:
    """Render non-Python text (JSON, transcripts) as an unhighlighted block."""
    return f'<pre class="code">{html.escape(source)}</pre>'


def term_block(source: str) -> str:
    """Render captured terminal output."""
    return f'<pre class="term">{html.escape(source)}</pre>'


def doc_block(source: str) -> str:
    """Render a Markdown document as preformatted text."""
    return f'<pre class="doc">{html.escape(source)}</pre>'


def file_label(rel: str) -> str:
    """Render the repo-relative path shown above a block."""
    return f'<div class="file">{html.escape(rel)}</div>'


def code_item(rel: str) -> str:
    """Load one Python file and render it as a labeled code block."""
    return file_label(rel) + code_block(read(rel))


def doc_item(rel: str) -> str:
    """Load one Markdown file and render it as a labeled document block."""
    return file_label(rel) + doc_block(read(rel))


def pending_box(rel: str, command: str) -> str:
    """Render the amber PENDING box for one missing evidence file."""
    return (
        f'<div class="pending"><b>PENDING:</b> {html.escape(rel)} is missing from '
        "this checkout, so the exhibit cannot be shown. Produce it, then rebuild "
        f'this PDF, with: <code>{html.escape(command)}</code></div>'
    )


def try_term(rel: str, command: str) -> str:
    """Render captured terminal output, or a PENDING box naming the producer."""
    if (ROOT / rel).exists():
        return file_label(rel) + term_block(read(rel))
    return pending_box(rel, command)


def class_excerpt(rel: str, class_name: str) -> str:
    """Slice exactly one top-level class out of a source file."""
    lines = read(rel).splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.startswith(f"class {class_name}")),
        None,
    )
    if start is None:
        raise ValueError(f"class {class_name} not found in {rel}")
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith(("class ", "def ")):
            end = i
            break
    excerpt = "\n".join(lines[start:end]).rstrip()
    ast.parse(excerpt)
    return excerpt


def between_excerpt(rel: str, start_marker: str, end_marker: str) -> str:
    """Slice a source file from start_marker up to (not including) end_marker.

    Guards the slice with ast.parse; a slice that does not parse falls back
    to the whole file so a broken cut can never ship silently garbled code.
    """
    source = read(rel)
    lines = source.splitlines()
    start = next((i for i, line in enumerate(lines) if start_marker in line), None)
    if start is None:
        return source
    end = next((i for i, line in enumerate(lines) if end_marker in line), len(lines))
    if end <= start:
        end = len(lines)
    excerpt = "\n".join(lines[start:end]).rstrip()
    try:
        ast.parse(excerpt)
    except SyntaxError:
        return source
    return excerpt


def phase_slice(rel: str, start_marker: str, stop_marker: str | None, command: str) -> str:
    """Slice one phase out of the captured deployment transcript.

    The deploy transcript is organized by "[N/5] PHASE" header lines; this
    returns the requested phase's lines, or a PENDING box when the transcript
    has not been captured yet.
    """
    path = ROOT / rel
    if not path.exists():
        return pending_box(rel, command)
    lines = read(rel).splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(start_marker)), None)
    if start is None:
        return pending_box(rel, command)
    end = len(lines)
    if stop_marker is not None:
        stop = next(
            (i for i, line in enumerate(lines) if line.startswith(stop_marker)), None
        )
        if stop is not None and stop > start:
            end = stop
    return term_block("\n".join(lines[start:end]).rstrip())


def section(num: int, title: str, body: str) -> str:
    """Wrap one numbered deliverable section, starting on a fresh page."""
    return f"<section><h2>{num}. {html.escape(title)}</h2>{body}</section>"


TOC: list[tuple[str, str]] = [
    ("1. IAM role and attached policy", "evidence/iam_role.txt, deploy/iam-policy.json, linter excerpt"),
    ("2. Building, pushing, deploying under the role", "deploy transcript phases 3-4 (evidence/aws_sim_run.txt)"),
    ("3. Deployment running and producing output", "deploy transcript phase 5 task log"),
    ("4. Networking configuration", "deploy transcript phase 1, deploy/network.json"),
    ("5. Ollama setup and the service code", "evidence/ollama_setup.txt, src/riskservice/"),
    ("6. On-prem run on the same input", "evidence/onprem_run.txt"),
    ("7. Deployment, networking, access controls document", "docs/deployment.md"),
    ("8. Cost/complexity/quality comparison", "docs/comparison.md"),
]

AWS_DEPLOY_CMD = "uv run python scripts/deploy_aws_sim.py --backend ollama | tee evidence/aws_sim_run.txt"


def build_cover() -> str:
    """Render the title page with its own A4 height and a mapped table of contents."""
    toc_rows = "".join(
        f"<tr><td>{html.escape(num_title)}</td><td>{html.escape(maps_to)}</td></tr>"
        for num_title, maps_to in TOC
    )
    return (
        '<div class="cover">'
        "<h1>Deploying the Risk Scoring Agent</h1>"
        '<div class="sub">Week 9 Lab Submission</div>'
        '<div class="line">One agent from the Week 8 underwriting pipeline '
        "(risk scoring), deployed two ways: to a simulated AWS environment "
        "(local simaws control plane: IAM, registry, tasks, network placement) "
        "and to a simulated on-prem environment (local Ollama), on the same "
        "frozen test input from the Week 8 traces.</div>"
        '<div class="line">No cloud service is used or called anywhere in this '
        "work; both targets are local simulations and are labeled as such in "
        "every artifact.</div>"
        '<div class="line repo">github.com/kenmann01/aws-upload</div>'
        '<div class="toc-title">Contents</div>'
        f"<table>{toc_rows}</table>"
        "</div>"
    )


CSS = """
@page { size: A4; margin: 16mm 15mm; }
* { box-sizing: border-box; }
body { font-family: 'Segoe UI', Arial, sans-serif; color: #111; margin: 0; }
.cover { height: 252mm; display: flex; flex-direction: column; justify-content: center; }
.cover h1 { font-size: 28pt; margin: 0 0 8px; }
.cover .sub { font-size: 13pt; color: #555; margin-bottom: 26px; }
.cover .line { font-size: 11.5pt; color: #333; margin: 0 0 10px; max-width: 168mm; }
.cover .repo { font-family: Consolas, monospace; color: #1f6feb; margin-bottom: 40px; }
.cover .toc-title { font-size: 13pt; font-weight: 600; color: #1f6feb; margin: 0 0 6px; }
.cover table { border-collapse: collapse; font-size: 10.5pt; max-width: 175mm; }
.cover td { padding: 4px 14px 4px 0; vertical-align: top; }
.cover td:first-child { color: #111; white-space: nowrap; }
.cover td:last-child { color: #555; }
h2 { font-size: 15.5pt; border-bottom: 2.5px solid #1f6feb; padding-bottom: 5px; margin: 0 0 14px; }
section { page-break-before: always; }
pre { margin: 7px 0 12px; padding: 10px 12px; border-radius: 6px; font-size: 8.1pt; line-height: 1.3; }
pre.term { background: #0d1117; color: #e6edf3; white-space: pre-wrap; word-break: break-word; font-family: Consolas, 'Courier New', monospace; }
pre.code { background: #f6f8fa; border: 1px solid #d0d7de; white-space: pre-wrap; word-break: break-word; font-family: Consolas, 'Courier New', monospace; }
pre.doc { background: #fffdf5; border: 1px solid #e3dcc3; white-space: pre-wrap; word-break: break-word; font-family: Consolas, 'Courier New', monospace; font-size: 8.4pt; }
pre.code .k { color: #cf222e; font-weight: 600; }
pre.code .s { color: #0a3069; }
pre.code .c { color: #6e7781; font-style: italic; }
.file { font-family: Consolas, monospace; font-size: 9pt; color: #1f6feb; margin: 12px 0 0; page-break-after: avoid; break-after: avoid; }
.note { font-size: 10pt; color: #444; margin: 8px 0 2px; }
.pending { background: #fff8e1; border: 1.5px solid #e0a800; color: #6b4d00; padding: 10px 12px; border-radius: 6px; font-size: 9.5pt; margin: 10px 0 14px; page-break-inside: avoid; }
.pending code { font-family: Consolas, monospace; background: #ffefb0; padding: 1px 5px; border-radius: 3px; }
"""


def build_html() -> str:
    """Assemble the eight deliverable sections into one HTML document."""
    p = [
        "<html><head><meta charset='utf-8'>"
        "<title>Deploying the Risk Scoring Agent, Week 9 Lab Submission</title>"
        f"<style>{CSS}</style></head><body>",
        build_cover(),
    ]

    # 1 IAM role and attached policy
    body1 = (
        '<div class="note">The task role with every permission justified, the '
        "linter that refuses wildcard or unjustified policies outright, and the "
        "get-role transcript showing the attached policy as stored in the "
        "simulated account.</div>"
        + try_term(IAM_ROLE, "uv run python -m simaws iam get-role --name risk-service-task --state .simaws/state.json")
        + file_label("deploy/iam-policy.json")
        + plain_block(read("deploy/iam-policy.json"))
        + '<div class="note">The least-privilege linter: wildcards and missing '
        "justifications are rejected before state is touched, so an over-broad "
        "policy cannot be attached even by accident.</div>"
        + file_label("src/simaws/iam.py, linter excerpt")
        + code_block(
            between_excerpt(
                "src/simaws/iam.py",
                "def validate_policy_document",
                "def put_role_policy",
            )
        )
    )
    p.append(section(1, "IAM role and attached policy", body1))

    # 2 building, pushing, deploying under the role
    body2 = (
        '<div class="note">Phases 3 and 4 of the deployment transcript: the '
        "image built and pushed with its digest, the task definition registered "
        "under the scoped role, and run-task authorizing (role actions, image "
        "digest, network placement) before executing anything.</div>"
        + phase_slice(AWS_RUN, "[3/5]", "[5/5]", AWS_DEPLOY_CMD)
    )
    p.append(section(2, "Building, pushing, deploying under the role", body2))

    # 3 deployment running and producing output
    body3 = (
        '<div class="note">Phase 5 of the deployment transcript: the task log '
        "with the service's scoring output on the frozen test input and the "
        "input hash.</div>"
        + phase_slice(AWS_RUN, "[5/5]", None, AWS_DEPLOY_CMD)
    )
    p.append(section(3, "Deployment running and producing output", body3))

    # 4 networking configuration
    body4 = (
        '<div class="note">Phase 1 of the deployment transcript: the placement '
        "validated against the least-privilege rules, then the committed "
        "placement document itself.</div>"
        + phase_slice(AWS_RUN, "[1/5]", "[2/5]", AWS_DEPLOY_CMD)
        + file_label("deploy/network.json")
        + plain_block(read("deploy/network.json"))
    )
    p.append(section(4, "Networking configuration", body4))

    # 5 ollama setup and the service code
    body5 = (
        '<div class="note">The model server inside the boundary: version, pulled '
        "model ids (the managed-endpoint stand-in qwen3:8b and the on-prem "
        "qwen3:4b), and the role the deployment issued the task.</div>"
        + try_term(OLLAMA_SETUP, "(ollama --version; ollama list; uv run python -m simaws iam get-role --name risk-service-task --state .simaws/state.json) | tee evidence/ollama_setup.txt")
        + '<div class="note">The deployed service: agent (factor-sum validation), '
        "service entrypoint, and CLI; the same bytes both targets run.</div>"
        + code_item("src/riskservice/agent.py")
        + code_item("src/riskservice/service.py")
        + file_label("src/riskservice/llm.py, OllamaClient excerpt")
        + code_block(class_excerpt("src/riskservice/llm.py", "OllamaClient"))
    )
    p.append(section(5, "Ollama setup and the service code", body5))

    # 6 on-prem run on the same input
    body6 = (
        '<div class="note">The simulated on-prem run: the same service, the '
        "same frozen input (the input hash is printed at the end), against the "
        "local boundary model server.</div>"
        + try_term(
            ONPREM_RUN,
            "uv run python scripts/deploy_onprem.py --backend ollama | tee evidence/onprem_run.txt",
        )
    )
    p.append(section(6, "On-prem run on the same input", body6))

    # 7 deployment document
    p.append(section(7, "Deployment, networking, and access controls", doc_item("docs/deployment.md")))

    # 8 comparison
    p.append(section(8, "Cost, complexity, and output quality comparison", doc_item("docs/comparison.md")))

    p.append("</body></html>")
    return "".join(p)


def browser_executable() -> str:
    """Headless Edge on Windows, otherwise the first Chromium-family binary on PATH."""
    windows = (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    )
    for candidate in windows:
        if Path(candidate).is_file():
            return candidate
    for name in ("microsoft-edge", "msedge", "chromium", "chromium-browser", "google-chrome"):
        found = shutil.which(name)
        if found:
            return found
    raise FileNotFoundError(
        "no headless browser found; install Edge or Chromium to print submission.pdf"
    )


def main() -> None:
    """Write submission.html and print it to submission.pdf with headless Edge or Chromium."""
    html_path = ROOT / "submission.html"
    html_path.write_text(build_html(), encoding="utf-8")

    pdf_path = ROOT / "submission.pdf"
    edge = browser_executable()
    subprocess.run(
        [
            edge,
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ],
        check=True,
        timeout=120,
    )

    size_bytes = pdf_path.stat().st_size
    print(f"wrote {html_path.name} and {pdf_path.name} ({size_bytes / 1024:.0f} KB, "
          "A4 pages; size is the health hint, page count not parsed)")
    if size_bytes < 20 * 1024:
        print(f"ERROR: submission.pdf is only {size_bytes / 1024:.1f} KB; "
              "Edge likely failed to print the document.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
