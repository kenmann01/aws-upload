# SPEC: Deploy the Week 8 Risk Scoring Agent (simulated AWS + simulated on-prem)

Status: ready-for-agent
Source: Week 9 lab brief (GenSpark FDE course), approved session plan 2026-10-17
Hard constraint: no cloud service is used or called (no AWS, Azure, GCP). All
"cloud" behavior is a local, hand-rolled simulation, stated plainly in every
artifact a grader sees.

## Problem Statement

The Week 8 multi-agent underwriting pipeline runs entirely on one laptop: one
process, one model, no access controls, no network boundary, no deployment
story. A client cannot tell from that artifact how the system would run inside
their environment, what it would be allowed to touch, or how the architecture
changes when their compliance rules forbid external services. The lab asks for
one agent from that pipeline deployed two ways (cloud and simulated on-prem),
with the access controls, networking, and architectural differences documented,
and an honest comparison of the two.

## Solution

A new self-contained repo carrying the risk scoring agent forward from Week 8.
The deployable unit is `riskservice`: it loads a frozen test input (the real
intake and enrichment states qwen3:8b produced in the Week 8 run), scores the
case, and prints the result with token usage. Two deployment paths wrap that
unit:

1. `simaws`, a local simulated AWS control plane with the parts the lab grades:
   IAM (roles, policies, a least-privilege linter that rejects wildcards and
   requires a written justification per statement), ECR-style image registry
   with digests, ECS-style task definitions and run-task that genuinely
   enforces the role (a task whose role cannot pull the image or write logs is
   denied before anything executes), and a VPC/subnet/security-group placement
   validator (private subnet for the task, no world-open ingress, egress
   limited to the model endpoint). `deploy_aws_sim.py` runs the full
   validate, IAM, build, push, deploy, run sequence and captures the
   transcript.
2. `deploy_onprem.py`, the same service against a local Ollama open-weight
   model, standing in for private model hosting inside a client boundary.

Both paths run the same frozen input and print the same input hash, so the
"both deployments confirmed working on the same test input" rubric line is
evidenced in the transcripts themselves. Documentation covers IAM permissions
and their justifications, networking reasoning, the architectural delta between
the two targets (citing this week's articles), and a cost/complexity/quality
comparison with a client-scenario recommendation.

## User Stories

1. As an FDE student, I want one agent from my Week 8 pipeline running as a
   standalone service, so that I have a real deployable unit rather than a
   notebook cell.
2. As an FDE student, I want both deployments to consume one frozen input file,
   so that the same-input rubric line is provable from the transcripts.
3. As an FDE student, I want the cloud half simulated locally, so that I learn
   the IAM and networking concepts without needing a cloud account or spending
   money.
4. As a grader, I want the IAM policy document to carry a justification string
   per statement, so that least privilege is demonstrated, not asserted.
5. As a grader, I want the simulator to reject wildcard actions and wildcard
   resources, so that "least privilege" is enforced by code, not prose.
6. As a grader, I want run-task to refuse to start a task whose role lacks the
   scoped permissions, so that "runs under that role" is a demonstrated
   behavior.
7. As a grader, I want the network placement validated (private subnet, no
   0.0.0.0/0 ingress, single-purpose egress), so that the networking rubric
   line maps to a checkable artifact.
8. As a grader, I want the submission PDF's eight sections to match the lab's
   eight required screenshots in order, so that grading is mechanical.
9. As a client with strict data residency rules, I want the on-prem path to
   keep applicant data inside the boundary (local model, local state), so that
   no processing step ships data to an external service.
10. As a client without residency constraints, I want the managed-style path's
    tradeoffs (cost, complexity, quality) quantified in the comparison, so that
    I can choose with evidence.
11. As an operator, I want deploy scripts to be idempotent, so that re-running
    a deployment updates resources instead of failing on duplicates.
12. As an operator, I want the deploy scripts to refuse to run against a dead
    model endpoint, so that a deployment never "succeeds" while producing
    nothing.
13. As an operator, I want task stdout captured to a log the simulator can
    redisplay, so that "the deployment produced output" is a first-class
    artifact.
14. As a course instructor, I want the simulation labeled as a simulation in
    every deliverable, so that the submission never misrepresents a local run
    as a real cloud deployment.
15. As the course's CI, I want the whole test suite to pass offline with a
    scripted model backend, so that green CI never depends on Ollama being up.

## Implementation Decisions

- The risk scoring agent, its Pydantic models, and the LLM client layer are
  ported from the Week 8 repo at `c0fd857` with provenance recorded in the
  README; only the pieces one standalone agent needs are carried over.
- The simulated control plane is a new package, not a fork of an existing AWS
  emulator: resource state is a local JSON store, ARNs use an `arn:simaws:`
  prefix, and policy documents gain one non-standard field, a required
  `justification` string per statement, which the linter enforces. This field
  exists to make the lab's "clear justification for each permission" criterion
  machine-checkable.
- ECS semantics follow the real service split: the task definition binds image,
  role, and environment; run-task carries network placement and the container
  command. run-task authorizes before executing: the role must allow the image
  pull on that repository and log writes to that log group, or the task fails
  with a denial and never runs.
- Image packaging uses Docker when a working Docker CLI is present (build then
  save, digest the artifact) and falls back to a deterministic source archive
  with the same digest discipline. The simulated runtime executes the verified
  task entrypoint in place; this is documented in the README and the deployment
  doc.
- The on-prem deployment differs from the cloud deployment only in model
  endpoint and model id, passed explicitly per script (cloud side defaults to
  qwen3:8b standing in for a managed endpoint; on-prem side defaults to a
  smaller open-weight model), so the comparison section compares two genuinely
  different model configurations.
- Environment variable names move from the Week 8 prefix to a
  service-specific prefix; host/model can also be passed per invocation.
- CI stays the Week 8 shape: uv sync, pytest with coverage, floor 97, no
  network dependency.
- All new text (docs, comments, commit messages) uses no em dashes, per the
  author's standing style rule.

## Testing Decisions

- Tests verify behavior through public interfaces only: the simaws CLI verb
  surface plus its state file, the riskservice entrypoint result and exit
  codes, the network validator's verdict list, and the two deploy scripts run
  end to end against the scripted backend.
- Four seams, agreed up front: (1) simaws CLI + state file, (2) riskservice
  entrypoint with a scripted model client, (3) the network config validator as
  a pure function, (4) the deploy scripts as subprocesses with their own state
  directories.
- Model behavior is deterministic in tests via the scripted client (marker
  keyed replies), never by mocking the agent's internals; existing Week 8 test
  style is the prior art.
- Expected values in tests come from worked literals (a known-good scripted
  reply whose factor points sum to its score), never from recomputing what the
  code computes.
- The coverage floor applies to the two source packages only; deploy scripts
  are exercised through subprocess runs, and the package `__main__` guards are
  excluded by pragma.

## Out of Scope

- Any real cloud API call, credential, or console screenshot; the simulation
  is labeled as such everywhere.
- Multi-agent deployment, pipeline retries, and fault injection: the lab deploys
  one agent.
- Real container orchestration features (service discovery, autoscaling,
  rollouts): the simulator models the graded subset (IAM, registry, task
  lifecycle, placement validation).
- vLLM or any production serving stack: Ollama remains the local model host,
  consistent with the course's own tooling.
- The Week 8 recommendation, intake, and enrichment agents: their recorded
  states appear only as the frozen input.

## Further Notes

The frozen test input embeds the Week 8 recorded risk output as a reference
field; the service never reads it. The submission PDF builder lands with amber
PENDING boxes for run-day evidence and is rebuilt once the real transcripts
exist, following the Week 8 pattern.
