# Tickets: aws-upload (Week 9 lab)

Tracer-bullet tickets building the Week 9 deliverable: one Week 8 agent
deployed to a simulated AWS environment and to a simulated on-prem Ollama
environment, with docs and a submission PDF. Source spec: SPEC.md.

Work the **frontier**: any ticket whose blockers are all done. For a purely
linear chain that means top to bottom.

## T1: Scaffold and CI

**What to build:** the repo skeleton works end to end: uv project with the two
source packages importable, pytest with a 97 coverage floor over the source
packages, GitHub Actions CI in the Week 8 shape, README with provenance, plus
SPEC.md and this tickets file. The suite is green with a packaging smoke test.

**Blocked by:** none, can start immediately.

- [ ] `uv sync` and `uv run pytest -q` both succeed on a fresh clone
- [ ] CI workflow file matches the Week 8 shape (checkout, setup-uv, sync, pytest with coverage)
- [ ] SPEC.md and tickets.md committed

## T2: riskservice, the deployable unit

**What to build:** `python -m riskservice --input <frozen input> --backend
scripted` loads the frozen intake and enrichment states, runs the risk scoring
agent, prints the result JSON plus a usage line, and exits 0. A dead model
endpoint exits 2 with a clear message. A model reply whose factor points do
not sum to its score surfaces as an error instead of a score.

**Blocked by:** T1 Scaffold and CI.

- [ ] scripted run on the frozen input exits 0 and prints score, factors, rationale, and usage
- [ ] factor-sum mismatch raises the agent output error, never a fabricated score
- [ ] ollama backend with an unreachable host exits 2 with the endpoint in the message
- [ ] frozen input file committed with the Week 8 trace provenance in its header

## T3: simaws IAM with a least-privilege linter

**What to build:** `simaws iam` verbs (create-role, put-role-policy, get-role)
over a local JSON state store. The policy linter rejects wildcard actions,
wildcard resources, and any statement without a written justification, so a
broad policy cannot be attached at all. get-role prints the role with its
attached policy for the evidence transcript.

**Blocked by:** T1 Scaffold and CI.

- [ ] create-role is idempotent-hostile: second create of the same name fails with a clear error
- [ ] a policy with any wildcard action or resource is rejected before touching state
- [ ] a policy statement missing its justification is rejected
- [ ] a valid scoped policy attaches and get-role displays it

## T4: simaws network placement validator

**What to build:** the network config (VPC, subnets, security groups, task
placement) as a committed JSON artifact plus a validator that enforces the
lab's networking story: the task sits in a private subnet, no world-open
ingress, and egress is a single rule to the model endpoint port. `simaws ec2
validate-network` prints PASS or the failing reasons; describe-network renders
the placement for the evidence transcript.

**Blocked by:** T1 Scaffold and CI.

- [ ] the committed placement passes validation
- [ ] public-subnet placement fails with a named reason
- [ ] 0.0.0.0/0 ingress fails with a named reason
- [ ] missing or extra egress fails with a named reason

## T5: simaws ECR and ECS run-task with IAM enforcement

**What to build:** `simaws ecr` (create-repository, push-image with digest,
describe-images) and `simaws ecs` (register-task-definition, run-task,
describe-task). run-task authorizes before executing: the task role must allow
the image pull on that repository and log writes, the image digest must exist,
and the network placement must validate, or the task is denied and nothing
runs. A started task executes the service entrypoint, captures stdout to a
task log, and records its final status.

**Blocked by:** T2 riskservice, T3 simaws IAM, T4 network placement validator.

- [ ] push-image records a digest and describe-images shows it (fallback packaging path covered by tests; docker path used when available)
- [ ] run-task with a role lacking pull or log permissions is denied with the missing actions named, and no task runs
- [ ] run-task with the scoped role runs the entrypoint, exits 0 on success, and the task log contains the score output
- [ ] describe-task shows status, exit code, and log content

## T6: Deploy scripts for both targets

**What to build:** `deploy_aws_sim.py` runs the whole sequence (validate
placement, upsert role and scoped policy, create repo, push image, register
task def, run task, print the task log) against the scripted backend offline
and the ollama backend on run day, idempotently, ending with the frozen
input's sha256. `deploy_onprem.py` health-checks the local model host (refuses
with exit 2 when down), runs the same service on the same frozen input with
the on-prem model id, and prints the same input hash. Both print transcripts
suitable for tee into evidence/.

**Blocked by:** T5 simaws ECR and ECS run-task.

- [ ] aws script on scripted backend exits 0 twice in a row (idempotent) with all five phases in the transcript
- [ ] onprem script on scripted backend exits 0 and prints the same input hash as the aws script
- [ ] onprem script with an unreachable model host exits 2 naming the endpoint
- [ ] the on-prem model id defaults to a smaller open-weight model than the cloud side

## T7: Deployment doc and comparison doc

**What to build:** docs/deployment.md: the IAM role's every permission with
its necessity tied to least privilege, the subnet and security-group reasoning,
and the architectural delta between the cloud-style and on-prem deployments,
citing this week's four articles. docs/comparison.md: cost, complexity, and
output quality for the two runs plus the recommendation for a strict-residency
client versus one without. Both state the simulation plainly.

**Blocked by:** T6 Deploy scripts, plus the four extracted Week 9 articles.

- [ ] every policy statement's justification maps to a sentence in the doc
- [ ] subnet choice and each security group rule have written reasoning
- [ ] the delta section names what changes and what stays, grounded in the articles
- [ ] the comparison answers the two client scenarios specifically

## T8: Submission PDF

**What to build:** the Week 8 style HTML-to-PDF builder rendering the lab's
eight required exhibits in order: IAM role and policy, build/push/deploy
transcript, cloud run output, networking config, Ollama setup and service
code, on-prem run on the same input, the deployment doc, the comparison.
Missing run-day evidence renders as amber PENDING boxes naming the producing
command; docs and source inputs fail loudly. Built and visually judged before
handoff, rebuilt after run day.

**Blocked by:** T7 Deployment doc and comparison doc.

- [ ] eight sections render in the brief's order
- [ ] PENDING boxes name the exact command that produces each missing exhibit
- [ ] visual judge passes all pages of the pre-run-day build
