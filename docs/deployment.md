# Deployment Document: the Risk Scoring Agent

Lab: Deploy an Agent to AWS and a Simulated On-Prem Environment (Week 9).
This document covers the three documentation requirements of the brief: the
IAM role and why each permission exists, the networking setup and its
reasoning, and what changes architecturally between the cloud-style deployment
and the simulated on-prem deployment.

## The simulation, stated plainly

No cloud service is used or called anywhere in this lab. The "AWS" side runs
on `simaws`, a local, hand-rolled control plane built for this lab: roles and
policies in a JSON state store with a least-privilege linter, an image
registry with digest discipline, task definitions and a run-task verb that
genuinely enforces the role before executing anything, and a network placement
validator. ARNs use an `arn:simaws:` prefix. The "on-prem" side runs the same
service against a local Ollama server. The lab brief itself frames the second
target as a simulation of what a real air-gapped deployment looks like at
small scale, and this submission extends the same honesty to the first target.

## What is deployed

One agent from the Week 8 multi-agent underwriting pipeline: the risk scoring
agent (`risk_scoring_agent`), packaged standalone as the `riskservice` service
(`python -m riskservice`). It loads two recorded upstream states (intake and
enrichment), scores the case 0 to 100 with an explained factor breakdown,
refuses any output whose factor points do not sum to the score, and prints
the result with token usage. Both deployments run the same frozen test input:
the real intake and enrichment states that qwen3:8b produced for CASE-001
(Dana Whitfield) in the committed Week 8 trace, lifted verbatim into
`deploy/input/test_input.json`. That file also records the Week 8 reference
output (score 15, three 5-point factors) as a human reference; the service
never reads it.

The risk scoring agent is one of the two agents the brief suggests: it is
self-contained, and its factor-sum check gives the deployment a hard,
verifiable notion of "produces a correct result" for the same-input
confirmation.

## The IAM role and why each permission exists

Article 1 (AWS, Azure, GCP Fundamentals, Use Case 1) makes the principle
concrete with this very pipeline: the risk scoring agent "should run under a
role with exactly those two permissions... nothing more", because a
compromised or buggy credential with broad permissions "could cause damage far
beyond what the agent actually needs to do its job." That principle, least
privilege, is enforced by code here in two layers:

1. The policy linter (`simaws iam put-role-policy`) rejects any statement with
   a wildcard action, a wildcard resource, or a missing justification, so an
   over-broad policy cannot be attached at all, even by accident.
2. `run-task` authorizes before executing: the task's role must grant the
   image pull on that exact repository and log writes to that exact log group,
   or the task is denied and nothing runs (demonstrated by the denial tests
   and repeatable from the evidence transcripts).

The role `risk-service-task` carries one policy (`deploy/iam-policy.json`)
with three statements:

| Statement | Actions | Resource | Why each action is necessary |
|---|---|---|---|
| PullServiceImage | ecr:GetAuthorizationToken, ecr:BatchGetImage, ecr:GetDownloadUrlForLayer | the one `risk-service` repository | The task must pull exactly its own service image. GetAuthorizationToken authenticates the registry pull; BatchGetImage and GetDownloadUrlForLayer fetch manifest and layers. No push actions (a workload that can rewrite its own image source is a supply-chain risk), no other repository (lateral movement). |
| WriteTaskLogs | logs:CreateLogStream, logs:PutLogEvents | the one `/simaws/risk-service` log group | The task appends its own run output so the deployment can be audited. Read and delete stay with operators; a workload that can erase its own logs defeats the audit trail. |
| CallModelEndpoint | bedrock:InvokeModel | one specific model id | In a real AWS deployment the model call would be InvokeModel on one specific Bedrock model id, keeping model access under the same IAM model as everything else (article 1, Use Case 3). The simulator routes this call to the private Ollama endpoint gated by the security group egress rule instead, and the simulator does not enforce this statement; it is in the policy because it documents the real deployment shape. |

The role's trust policy allows assumption by the ECS task scheduler principal
only (`ecs-tasks.amazonaws.com`, the real service principal name), matching
the "roles are assumed by services, not hardcoded users" idea from article 1.

## Networking setup and reasoning

The placement lives in `deploy/network.json` and is validated by
`simaws ec2 validate-network` before anything deploys (article 1, Use Case 2:
internal services sit in private subnets and "should never be directly
reachable from outside"):

- VPC `vpc-0fde9001` (10.9.0.0/16), simulated.
- Three subnets: a public one reserved for a future entry point, and two
  private ones, application (10.9.1.0/24) and model (10.9.2.0/24).
- The task is placed in the **private application subnet**. The service is
  outbound-only: it receives no traffic, it scores a case and returns. A
  private subnet removes any direct internet path, and the validator rejects
  placement in a public subnet outright.
- Security group `sg-0fde9001risk`: **no ingress rules at all** (there is no
  inbound flow to allow, so none is opened; the validator rejects any
  world-open 0.0.0.0/0 ingress), and **exactly one egress rule**: tcp/11434 to
  the private model subnet (10.9.2.0/24), justified on the rule itself. The
  validator rejects any second egress rule, so the blast radius of a
  compromised task is one port to one subnet.
- The model endpoint sits in its own private subnet so that "the model runs
  inside our network boundary" is represented in the topology, the on-prem
  story in miniature.

The failure mode this guards against is the misconfigured-security-group
incident class: a task that can reach the whole internet can exfiltrate the
applicant data it scores. One egress rule to one internal subnet makes that
impossible by construction rather than by vigilance.

## The deployment flow (ECR + ECS path)

`scripts/deploy_aws_sim.py` runs the same sequence as the Week 3 console path,
in order, and its output is the deployment transcript:

1. validate the network placement;
2. create (or reuse) the task role, lint and attach the scoped policy;
3. create the repository, build and push the image (Docker build+save when a
   working Docker daemon is present, else a deterministic source archive with
   the same sha256 digest discipline);
4. register the task definition (image, role, environment), then run-task,
   which verifies the role's actions, the pushed digest, and the placement
   before executing anything;
5. print the task log: the service's scoring output on the frozen input.

## What changes architecturally for on-prem

Article 3 (On-Prem Realities, Use Case 3) answers this for the whole pipeline:
"the agent logic... stays conceptually identical; what changes is where the
model itself lives and how your code reaches it." Concretely in this lab:

- **What stays the same:** the service code, the agent, the factor-sum
  validation, the frozen input, the result schema. `riskservice` is byte-for-byte
  the same service in both deployments.
- **What changes:** only the model endpoint and model id. The cloud-style
  task calls a "managed endpoint" (qwen3:8b standing in, under the
  CallModelEndpoint statement's real-architecture story); the on-prem
  deployment calls the local Ollama server hosting a smaller open-weight
  model (qwen3:4b), selected by one flag. No code changes between the two:
  the endpoint is configuration, exactly the property article 3 describes.
- **What the air-gap would additionally demand** (article 3, Use Case 1):
  every dependency pre-staged through an approved transfer instead of pulled
  live (base images, Python packages, model weights), and updates moving at
  the client's audit pace, not at pip's. This lab's own equivalents are the
  committed artifacts: the image artifact with its recorded digest, the pinned
  model ids, and the frozen input.
- **Why a client demands it** (article 4): data residency and sovereignty
  (Use Cases 1 and 2: an inference call is a data transfer and can cross a
  jurisdiction), third-party vendor risk (Use Case 3: each external service
  triggers a formal review), and model risk management (Use Case 4: a
  self-hosted, version-pinned model can be frozen and validated; an external
  API can change underneath an audited decision). The on-prem variant here is
  version-pinned by model id, which is precisely the property article 4
  says regulated clients need.

## Evidence index

| Brief deliverable | Where |
|---|---|
| IAM role and attached policy | exhibit 1 (get-role transcript, `deploy/iam-policy.json`) |
| Build/push/deploy terminal output | exhibit 2 (`evidence/aws_sim_run.txt`, phases 2 to 4) |
| Cloud deployment running on the test input | exhibit 3 (`evidence/aws_sim_run.txt`, phase 5 task log) |
| Networking configuration | exhibit 4 (validate + describe transcript, `deploy/network.json`) |
| Ollama setup and service code | exhibit 5 (`evidence/ollama_setup.txt`, `src/riskservice/`) |
| On-prem run on the same input | exhibit 6 (`evidence/onprem_run.txt`) |
| This document | exhibit 7 |
| Cost/complexity/quality comparison | exhibit 8 (`docs/comparison.md`) |

The input hash printed at the end of both run transcripts is the shared
sha256 of `deploy/input/test_input.json`: one line, identical in both, which
is the same-test-input confirmation.
