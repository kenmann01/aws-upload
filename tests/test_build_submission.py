"""Unit tests for scripts/build_submission.py, the submission PDF builder.

The scripts/ directory is not an installed package, so the module is loaded
straight from its file path. The evidence/*.txt exhibits are run-day
artifacts that do not exist in a fresh checkout, so several tests assert the
amber PENDING fallback instead of captured output.
"""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "build_submission", REPO_ROOT / "scripts" / "build_submission.py"
)
if _spec is None or _spec.loader is None:  # pragma: no cover
    raise ImportError("cannot load scripts/build_submission.py")
bs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bs)

# The eight h2 headings build_html() must render, in the brief's order.
SECTION_TITLES = [
    ">1. IAM role and attached policy",
    ">2. Building, pushing, deploying under the role",
    ">3. Deployment running and producing output",
    ">4. Networking configuration",
    ">5. Ollama setup and the service code",
    ">6. On-prem run on the same input",
    ">7. Deployment, networking, and access controls",
    ">8. Cost, complexity, and output quality comparison",
]


def test_build_html_has_eight_sections_and_pending_boxes():
    html = bs.build_html()
    for title in SECTION_TITLES:
        assert title in html, f"missing section heading {title!r}"
    evidence = [
        "evidence/iam_role.txt",
        "evidence/aws_sim_run.txt",
        "evidence/ollama_setup.txt",
        "evidence/onprem_run.txt",
    ]
    # aws_sim_run.txt backs sections 2, 3, and 4, so a checkout missing all
    # four files renders six PENDING boxes. Once the transcripts are captured,
    # those boxes are gone and the shared input hash is in the page.
    if all((bs.ROOT / rel).is_file() for rel in evidence):
        assert 'class="pending"' not in html
        assert "input_sha256:" in html
    else:
        assert html.count('class="pending"') == 6


def test_phase_slice_missing_file_returns_pending():
    out = bs.phase_slice("evidence/nope.txt", "[1/5]", "[2/5]", "some cmd")
    assert "PENDING" in out
    assert "some cmd" in out


def test_phase_slice_cuts_requested_phase(tmp_path, monkeypatch):
    (tmp_path / "t.txt").write_text(
        "header\n[1/5] NETWORK\npass line\n[2/5] IAM\nrole line\n", encoding="utf-8"
    )
    monkeypatch.setattr(bs, "ROOT", tmp_path)
    out = bs.phase_slice("t.txt", "[1/5]", "[2/5]", "cmd")
    assert "pass line" in out
    assert "role line" not in out
    assert "header" not in out
    # A None stop marker runs the slice to end of file.
    to_eof = bs.phase_slice("t.txt", "[1/5]", None, "cmd")
    assert "pass line" in to_eof
    assert "role line" in to_eof


def test_phase_slice_missing_marker_returns_pending(tmp_path, monkeypatch):
    (tmp_path / "t.txt").write_text("no markers in this transcript\n", encoding="utf-8")
    monkeypatch.setattr(bs, "ROOT", tmp_path)
    out = bs.phase_slice("t.txt", "[9/9]", None, "capture it")
    assert "PENDING" in out
    assert "capture it" in out


def test_between_excerpt_slices_and_guards():
    rel = "src/simaws/iam.py"
    out = bs.between_excerpt(rel, "def validate_policy_document", "def put_role_policy")
    assert out.startswith("def validate_policy_document")
    assert "def put_role_policy" not in out
    # A start marker that matches nothing falls back to the whole file.
    whole = bs.between_excerpt(rel, "def definitely_not_a_marker", "def put_role_policy")
    assert whole == (bs.ROOT / rel).read_text(encoding="utf-8").rstrip()


def test_class_excerpt_slices_ollama_client():
    out = bs.class_excerpt("src/riskservice/llm.py", "OllamaClient")
    assert out.startswith("class OllamaClient")
    assert "class ScriptedClient" not in out
    assert out == out.rstrip()


def test_try_term_pending_and_present(tmp_path, monkeypatch):
    missing = bs.try_term("evidence/missing_run.txt", "make evidence")
    assert "PENDING" in missing
    assert "make evidence" in missing

    (tmp_path / "t.txt").write_text("boot ok\nlistening on port 8000\n", encoding="utf-8")
    monkeypatch.setattr(bs, "ROOT", tmp_path)
    present = bs.try_term("t.txt", "run it")
    assert "boot ok" in present
    assert '<pre class="term">' in present
